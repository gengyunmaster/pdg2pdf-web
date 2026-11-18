// pdgdrive.c — Win32 message-level driver for Pdg2Pic.exe (Phase A).
//
// Strategy: the app persists its state to Pdg2Pic.ini (UTF-16LE, BOM,
// [ParaBlock] section) and restores it at startup. We pre-seed that ini
// with the source directory (PARA_DIR_SRC) and the target PDF path
// (PARA_DIR_TGT + PARA_TGT_TYPE=1), launch the app, click the start
// button (control ID 1, the on-screen "4" step), then watch for the PDF
// and dismiss completion/error popups. No coordinate automation anywhere.
//
// Control IDs verified live under Wine with windowdump.exe (see
// scripts/recon.sh). Exit codes:
//   0 ok (prints "PDF=<path>")   2 usage/app-missing   3 window/control
//   5 timeout                    6 fatal popup

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <commctrl.h>
#include <objbase.h>
#include <shlobj.h>

#define SRC_EDIT_ID   1066   /* 0x42a  source folder edit                */
#define FILE_LIST_ID  1006   /* 0x3ee  SysListView32                     */
#define START_BTN_ID  1      /* IDOK, the on-screen "4 开始转换" button  */
#define SRC_BROWSE_ID   1004 /* 0x3ec  opens the folder picker             */
#define PICKER_OK_ID    1    /* picker's 确定 button                      */

static DWORD g_app_pid = 0;
static HWND  g_main = NULL;
static PROCESS_INFORMATION g_pi = {0};
static WCHAR g_watch_dir[MAX_PATH] = {0};
static HANDLE g_app_proc = NULL;

/* Chinese popup keywords as \uXXXX escapes (encoding-agnostic source). */
static const WCHAR TXT_OK_DONE[] =
    {0x8f6c,0x6362,0x5b8c,0x6bd5,0};                    /* 转换完毕 */
static const WCHAR TXT_ERR1[] = {0x9519,0x8bef,0};      /* 错误 */
static const WCHAR TXT_ERR2[] = {0x5931,0x8d25,0};      /* 失败 */
static const WCHAR TXT_ERR3[] = {0x62b1,0x6b49,0};      /* 抱歉 */
static const WCHAR TXT_ERR4[] = {0x6ca1,0x6709,0};      /* 没有 */

static void kill_app(void) {
    if (g_pi.hProcess) {
        TerminateProcess(g_pi.hProcess, 0);
        WaitForSingleObject(g_pi.hProcess, 3000);
        CloseHandle(g_pi.hProcess);
        CloseHandle(g_pi.hThread);
        g_pi.hProcess = NULL;
    }
}

static void utf8_print(FILE *f, const WCHAR *w) {
    if (w && w[0]) {
        int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, NULL, 0, NULL, NULL);
        if (n > 0) {
            char *buf = (char *)malloc((size_t)n);
            if (buf) {
                WideCharToMultiByte(CP_UTF8, 0, w, -1, buf, n, NULL, NULL);
                fputs(buf, f);
                free(buf);
                return;
            }
        }
    }
    fputs("\n", f);
}

static void dump_popup_text(HWND popup, WCHAR *buf, size_t cap) {
    size_t used = 0;
    buf[0] = 0;
    WCHAR cls[64], t[512];
    HWND child = NULL;
    while ((child = FindWindowExW(popup, child, NULL, NULL)) != NULL) {
        GetClassNameW(child, cls, 63);
        if (wcsstr(cls, L"Static") == NULL && wcsstr(cls, L"Button") == NULL)
            continue;
        if (GetWindowTextW(child, t, 511) > 0) {
            int n = _snwprintf(buf + used, cap - used - 1, L"%s ", t);
            if (n > 0) used += (size_t)n;
        }
    }
    if (used == 0)
        GetWindowTextW(popup, buf, (int)cap - 1);
}

struct popup_info { HWND hwnd; WCHAR text[1024]; };

static BOOL CALLBACK popup_enum(HWND hwnd, LPARAM lp) {
    struct popup_info *pi = (struct popup_info *)lp;
    WCHAR cls[64] = {0};
    DWORD pid = 0;
    GetClassNameW(hwnd, cls, 63);
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid == g_app_pid && hwnd != g_main && wcscmp(cls, L"#32770") == 0) {
        dump_popup_text(hwnd, pi->text, sizeof(pi->text) / sizeof(WCHAR));
        pi->hwnd = hwnd;
        return FALSE;
    }
    return TRUE;
}

static BOOL CALLBACK main_enum(HWND hwnd, LPARAM lp) {
    WCHAR cls[64] = {0}, title[256] = {0};
    (void)lp;
    GetClassNameW(hwnd, cls, 63);
    GetWindowTextW(hwnd, title, 255);
    if (wcscmp(cls, L"#32770") == 0 && wcscmp(title, L"Pdg2Pic") == 0 &&
        FindWindowExW(hwnd, NULL, L"SysListView32", NULL)) {
        g_main = hwnd;
        GetWindowThreadProcessId(hwnd, &g_app_pid);
        return FALSE;
    }
    return TRUE;
}

static BOOL CALLBACK dbg_dump(HWND hwnd, LPARAM lp) {
    WCHAR cls[64] = {0}, title[256] = {0};
    DWORD pid = 0;
    (void)lp;
    GetClassNameW(hwnd, cls, 63);
    GetWindowTextW(hwnd, title, 255);
    GetWindowThreadProcessId(hwnd, &pid);
    fprintf(stderr, "  win pid=%lu cls=", pid);
    utf8_print(stderr, cls);
    fprintf(stderr, " title=");
    utf8_print(stderr, title);
    return TRUE;
}


/* ---- minimal OLE drag source (IDataObject + IDropSource) ------------- */
typedef struct {
    IDataObject iface;
    LONG refs;
    HGLOBAL hdrop;
} DropObj;

static HRESULT STDMETHODCALLTYPE do_QueryInterface(IUnknown *self, REFIID riid, void **pp) {
    if (!pp) return E_POINTER;
    *pp = NULL;
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IDataObject)) {
        *pp = self; self->lpVtbl->AddRef(self); return S_OK;
    }
    return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE do_AddRef(IUnknown *self) {
    DropObj *d = (DropObj *)self;
    return InterlockedIncrement(&d->refs);
}
static ULONG STDMETHODCALLTYPE do_Release(IUnknown *self) {
    DropObj *d = (DropObj *)self;
    LONG r = InterlockedDecrement(&d->refs);
    if (r == 0) { if (d->hdrop) GlobalFree(d->hdrop); free(d); }
    return r;
}
static HRESULT STDMETHODCALLTYPE do_GetData(IDataObject *self, FORMATETC *fmt, STGMEDIUM *med) {
    DropObj *d = (DropObj *)self;
    if (!fmt || !med) return E_POINTER;
    if (fmt->cfFormat != CF_HDROP || fmt->dwAspect != DVASPECT_CONTENT ||
        fmt->tymed != TYMED_HGLOBAL) return DV_E_FORMATETC;
    med->tymed = TYMED_HGLOBAL;
    {
        SIZE_T sz = GlobalSize(d->hdrop);
        med->hGlobal = GlobalAlloc(GMEM_MOVEABLE, sz);
        if (!med->hGlobal) return E_OUTOFMEMORY;
        void *dst = GlobalLock(med->hGlobal);
        void *srcl = GlobalLock(d->hdrop);
        memcpy(dst, srcl, sz);
        GlobalUnlock(med->hGlobal);
        GlobalUnlock(d->hdrop);
    }
    med->pUnkForRelease = NULL;
    return S_OK;
}
static HRESULT STDMETHODCALLTYPE do_GetDataHere(IDataObject *self, FORMATETC *fmt, STGMEDIUM *med) {
    (void)self; (void)fmt; (void)med; return DV_E_TYMED;
}
static HRESULT STDMETHODCALLTYPE do_QueryGetData(IDataObject *self, FORMATETC *fmt) {
    (void)self;
    if (!fmt) return E_POINTER;
    if (fmt->cfFormat != CF_HDROP || fmt->dwAspect != DVASPECT_CONTENT ||
        fmt->tymed != TYMED_HGLOBAL) return DV_E_FORMATETC;
    return S_OK;
}
static HRESULT STDMETHODCALLTYPE do_GetCanonicalFormatEtc(IDataObject *self, FORMATETC *in, FORMATETC *out) {
    (void)self; (void)in; if (out) out->ptd = NULL; return E_NOTIMPL;
}
static HRESULT STDMETHODCALLTYPE do_SetData(IDataObject *self, FORMATETC *fmt, STGMEDIUM *med, BOOL release) {
    (void)self; (void)fmt; (void)med; (void)release; return E_NOTIMPL;
}
typedef struct {
    IEnumFORMATETC iface;
    LONG refs;
    ULONG pos;
} EnumFmt;

static HRESULT STDMETHODCALLTYPE ef_QueryInterface(IUnknown *self, REFIID riid, void **pp) {
    if (!pp) return E_POINTER;
    *pp = NULL;
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IEnumFORMATETC)) {
        *pp = self; self->lpVtbl->AddRef(self); return S_OK;
    }
    return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE ef_AddRef(IUnknown *self) {
    EnumFmt *e = (EnumFmt *)self; return InterlockedIncrement(&e->refs);
}
static ULONG STDMETHODCALLTYPE ef_Release(IUnknown *self) {
    EnumFmt *e = (EnumFmt *)self; LONG r = InterlockedDecrement(&e->refs);
    if (r == 0) free(e); return r;
}
static HRESULT STDMETHODCALLTYPE ef_Next(IEnumFORMATETC *self, ULONG n, FORMATETC *arr, ULONG *got) {
    EnumFmt *e = (EnumFmt *)self;
    ULONG i = 0;
    static const FORMATETC fmt = { CF_HDROP, NULL, DVASPECT_CONTENT, -1, TYMED_HGLOBAL };
    while (i < n && e->pos == 0) { arr[i++] = fmt; e->pos++; }
    if (got) *got = i;
    return i == n ? S_OK : S_FALSE;
}
static HRESULT STDMETHODCALLTYPE ef_Skip(IEnumFORMATETC *self, ULONG n) {
    EnumFmt *e = (EnumFmt *)self;
    if (e->pos + n > 1) { e->pos = 1; return S_FALSE; }
    e->pos += n; return S_OK;
}
static HRESULT STDMETHODCALLTYPE ef_Reset(IEnumFORMATETC *self) {
    ((EnumFmt *)self)->pos = 0; return S_OK;
}
static HRESULT STDMETHODCALLTYPE ef_Clone(IEnumFORMATETC *self, IEnumFORMATETC **pp) {
    EnumFmt *e = (EnumFmt *)self;
    if (!pp) return E_POINTER;
    EnumFmt *c = (EnumFmt *)calloc(1, sizeof(EnumFmt));
    if (!c) return E_OUTOFMEMORY;
    c->iface.lpVtbl = self->lpVtbl;
    c->refs = 1;
    c->pos = e->pos;
    *pp = (IEnumFORMATETC *)c;
    return S_OK;
}
static IEnumFORMATETCVtbl ef_vtbl = {
    ef_QueryInterface, ef_AddRef, ef_Release,
    ef_Next, ef_Skip, ef_Reset, ef_Clone
};

static HRESULT STDMETHODCALLTYPE do_EnumFormatEtc(IDataObject *self, DWORD dir, IEnumFORMATETC **pp) {
    (void)self;
    if (!pp) return E_POINTER;
    *pp = NULL;
    if (dir != DATADIR_GET) return E_NOTIMPL;
    EnumFmt *e = (EnumFmt *)calloc(1, sizeof(EnumFmt));
    if (!e) return E_OUTOFMEMORY;
    e->iface.lpVtbl = &ef_vtbl;
    e->refs = 1;
    *pp = (IEnumFORMATETC *)e;
    return S_OK;
}
static HRESULT STDMETHODCALLTYPE do_DAdvise(IDataObject *self, FORMATETC *fmt, DWORD advf, IAdviseSink *sink, DWORD *conn) {
    (void)self; (void)fmt; (void)advf; (void)sink; (void)conn; return OLE_E_ADVISENOTSUPPORTED;
}
static HRESULT STDMETHODCALLTYPE do_DUnadvise(IDataObject *self, DWORD conn) {
    (void)self; (void)conn; return OLE_E_ADVISENOTSUPPORTED;
}
static HRESULT STDMETHODCALLTYPE do_EnumDAdvise(IDataObject *self, IEnumSTATDATA **pp) {
    (void)self; (void)pp; return OLE_E_ADVISENOTSUPPORTED;
}
static IDataObjectVtbl do_vtbl = {
    do_QueryInterface, do_AddRef, do_Release,
    do_GetData, do_GetDataHere, do_QueryGetData,
    do_GetCanonicalFormatEtc, do_SetData, do_EnumFormatEtc,
    do_DAdvise, do_DUnadvise, do_EnumDAdvise
};

typedef struct { IDropSource iface; LONG refs; int calls; } DropSrc;
static ULONG STDMETHODCALLTYPE ds_AddRef(IUnknown *self) {
    DropSrc *d = (DropSrc *)self; return InterlockedIncrement(&d->refs);
}
static HRESULT STDMETHODCALLTYPE ds_QueryInterface(IUnknown *self, REFIID riid, void **pp) {
    if (!pp) return E_POINTER;
    *pp = NULL;
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IDropSource)) {
        *pp = self; self->lpVtbl->AddRef(self); return S_OK;
    }
    return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE ds_Release(IUnknown *self) {
    DropSrc *d = (DropSrc *)self; LONG r = InterlockedDecrement(&d->refs);
    if (r == 0) free(d); return r;
}
static HRESULT STDMETHODCALLTYPE ds_QueryContinueDrag(IDropSource *self, BOOL escape, DWORD keys) {
    DropSrc *d = (DropSrc *)self;
    (void)escape; (void)keys;
    /* first S_OK lets the loop resolve the target under the cursor;
     * the second call performs the drop */
    if (d->calls++ == 0) return S_OK;
    return DRAGDROP_S_DROP;
}
static HRESULT STDMETHODCALLTYPE ds_GiveFeedback(IDropSource *self, DWORD effect) {
    (void)self; (void)effect; return (HRESULT)0x80040100L; /* DRAGDROP_S_FIRST: use default cursor */
}
static IDropSourceVtbl ds_vtbl = {
    ds_QueryInterface, ds_AddRef, ds_Release,
    ds_QueryContinueDrag, ds_GiveFeedback
};

/* Build an HDROP holding one wide path. */
static HGLOBAL make_hdrop(const WCHAR *dir) {
    size_t len = wcslen(dir) + 1;
    typedef struct { DWORD pFiles; POINT pt; BOOL fNC; BOOL fWide; } DF;
    HGLOBAL h = GlobalAlloc(GMEM_MOVEABLE, sizeof(DF) + (len + 1) * sizeof(WCHAR));
    if (!h) return NULL;
    DF *df = (DF *)GlobalLock(h);
    df->pFiles = sizeof(DF); df->pt.x = df->pt.y = 0;
    df->fNC = FALSE; df->fWide = TRUE;
    memcpy((char *)df + sizeof(DF), dir, len * sizeof(WCHAR));
    ((WCHAR *)((char *)df + sizeof(DF)))[len] = 0;
    GlobalUnlock(h);
    return h;
}

/* Perform an OLE drop of `dir` at (x,y) in screen coordinates. */
static int ole_drop_at(const WCHAR *dir, int x, int y) {
    DropObj *obj = (DropObj *)calloc(1, sizeof(DropObj));
    DropSrc *src = (DropSrc *)calloc(1, sizeof(DropSrc));
    if (!obj || !src) { free(obj); free(src); return 0; }
    obj->iface.lpVtbl = &do_vtbl;
    obj->refs = 1;
    obj->hdrop = make_hdrop(dir);
    src->iface.lpVtbl = &ds_vtbl;
    src->refs = 1;
    {
        int sw = GetSystemMetrics(SM_CXSCREEN), sh = GetSystemMetrics(SM_CYSCREEN);
        INPUT in = {0};
        in.type = INPUT_MOUSE;
        in.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
        in.mi.dx = (LONG)((x * 65535L) / (sw > 0 ? sw : 1));
        in.mi.dy = (LONG)((y * 65535L) / (sh > 0 ? sh : 1));
        SendInput(1, &in, sizeof(in));
    }
    Sleep(600);
    {
        POINT cur; GetCursorPos(&cur);
        HWND under = WindowFromPoint(cur);
        WCHAR cls[64] = {0};
        if (under) GetClassNameW(under, cls, 63);
        fprintf(stderr, "pdgdrive: cursor %d,%d (want %d,%d) under cls=",
                cur.x, cur.y, x, y);
        utf8_print(stderr, cls);
    }
    DWORD effect = 0;
    HRESULT hr = DoDragDrop((IDataObject *)obj, (IDropSource *)src,
                            DROPEFFECT_COPY, &effect);
    fprintf(stderr, "pdgdrive: DoDragDrop hr=%08lx effect=%lu\n",
            (unsigned long)hr, (unsigned long)effect);
    obj->iface.lpVtbl->Release((IDataObject *)obj);
    src->iface.lpVtbl->Release((IDropSource *)src);
    return SUCCEEDED(hr);
}

/* Wine exposes the container filesystem under drive Z:. Convert a Unix
 * path (/srv/data/x) to what a Windows program understands (Z:\srv\data\x). */
static void unix_to_win(const WCHAR *in, WCHAR *out, size_t cap) {
    size_t o = 0;
    if (in[0] == L'/' && cap > 4) { out[o++] = L'Z'; out[o++] = L':'; }
    for (size_t i = 0; in[i] && o + 1 < cap; i++)
        out[o++] = (in[i] == L'/') ? L'\\' : in[i];
    out[o] = 0;
}

struct find_ctx2 { UINT id; HWND found; };

static BOOL CALLBACK find_edit(HWND hwnd, LPARAM lp) {
    struct find_ctx2 *c = (struct find_ctx2 *)lp;
    WCHAR cls[64] = {0};
    GetClassNameW(hwnd, cls, 63);
    if (!wcscmp(cls, L"Edit")) { c->found = hwnd; return FALSE; }
    return TRUE;
}
static HWND find_first_edit(HWND root) {
    struct find_ctx2 c = { 0, NULL };
    EnumChildWindows(root, find_edit, (LPARAM)&c);
    return c.found;
}


static BOOL CALLBACK find_by_class_tree(HWND hwnd, LPARAM lp) {
    struct find_ctx2 *c = (struct find_ctx2 *)lp;
    WCHAR cls[64] = {0};
    GetClassNameW(hwnd, cls, 63);
    if (!wcscmp(cls, L"SysTreeView32")) { c->found = hwnd; return FALSE; }
    return TRUE;
}

static BOOL CALLBACK find_by_id(HWND hwnd, LPARAM lp) {
    struct find_ctx2 *c = (struct find_ctx2 *)lp;
    if ((UINT)GetDlgCtrlID(hwnd) == c->id) { c->found = hwnd; return FALSE; }
    return TRUE;
}
static HWND find_ctrl(HWND root, UINT id) {
    struct find_ctx2 c = { id, NULL };
    EnumChildWindows(root, find_by_id, (LPARAM)&c);
    return c.found;
}


/* ---- cross-process tree-view access ------------------------------- */
static int ci_eq(const WCHAR *a, const WCHAR *b) {
    while (*a && *b) {
        WCHAR x = *a, y = *b;
        if (x >= L'A' && x <= L'Z') x += 32;
        if (y >= L'A' && y <= L'Z') y += 32;
        if (x != y) return 0;
        a++; b++;
    }
    return *a == 0 && *b == 0;
}

static int remote_item_text(HWND tree, HTREEITEM item, WCHAR *out, size_t cap) {
    SIZE_T need = sizeof(TVITEMW) + cap * sizeof(WCHAR);
    LPVOID base = VirtualAllocEx(g_app_proc, NULL, need, MEM_COMMIT, PAGE_READWRITE);
    if (!base) return 0;
    TVITEMW ti;
    ZeroMemory(&ti, sizeof(ti));
    ti.mask = TVIF_TEXT | TVIF_HANDLE;
    ti.hItem = item;
    ti.pszText = (LPWSTR)((char *)base + sizeof(TVITEMW));
    ti.cchTextMax = (int)cap - 1;
    SIZE_T wr = 0;
    if (!WriteProcessMemory(g_app_proc, base, &ti, sizeof(ti), &wr) ||
        wr < sizeof(ti)) { VirtualFreeEx(g_app_proc, base, 0, MEM_RELEASE); return 0; }
    LRESULT ok = SendMessageW(tree, TVM_GETITEMW, 0, (LPARAM)base);
    if (!ok) { VirtualFreeEx(g_app_proc, base, 0, MEM_RELEASE); return 0; }
    ZeroMemory(out, cap * sizeof(WCHAR));
    SIZE_T rd = 0;
    ReadProcessMemory(g_app_proc, ti.pszText, out, (cap - 1) * sizeof(WCHAR), &rd);
    VirtualFreeEx(g_app_proc, base, 0, MEM_RELEASE);
    out[cap - 1] = 0;
    return 1;
}

static HTREEITEM find_child_by_text(HWND tree, HTREEITEM parent,
                                    const WCHAR *name) {
    HTREEITEM it = (HTREEITEM)SendMessageW(
        tree, TVM_GETNEXTITEM, parent ? TVGN_CHILD : TVGN_ROOT, (LPARAM)parent);
    while (it) {
        WCHAR t[256] = {0};
        if (remote_item_text(tree, it, t, 256) && ci_eq(t, name)) return it;
        it = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, (LPARAM)it);
    }
    return NULL;
}

/* Walk the picker tree to winpath (e.g. Z:\tmp\w), expanding and
 * selecting each component. Returns 1 when the leaf got the caret. */
static int pick_path_in_tree(HWND tree, const WCHAR *winpath) {
    if (!tree || !g_app_proc) return 0;
    WCHAR buf[MAX_PATH] = {0};
    wcsncpy(buf, winpath, MAX_PATH - 1);
    /* split into components on backslash */
    WCHAR *comps[32]; int nc = 0;
    WCHAR *p = buf;
    while (*p && nc < 32) {
        while (*p == L'\\') p++;
        if (!*p) break;
        comps[nc++] = p;
        while (*p && *p != L'\\') p++;
        if (*p) *p++ = 0;
    }
    HTREEITEM cur = NULL;
    for (int i = 0; i < nc; i++) {
        const WCHAR *comp = comps[i];
        HTREEITEM next = find_child_by_text(tree, cur, comp);
        if (!next && i == 0 && comp[1] == L':') {
            /* namespace: Desktop -> My Computer -> drives */
            static const WCHAR MC_ZH[] = {0x6211,0x7684,0x7535,0x8111,0}; /* 我的电脑 */
            HTREEITEM desk = cur ? cur
                : (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0);
            if (desk) {
                SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)desk);
                Sleep(400);
                HTREEITEM mc = find_child_by_text(tree, desk, L"My Computer");
                if (!mc) mc = find_child_by_text(tree, desk, MC_ZH);
                if (mc) {
                    SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)mc);
                    Sleep(400);
                    cur = mc;
                    next = find_child_by_text(tree, cur, comp);
                }
            }
        }
        if (!next && cur && i == 1) {
            WCHAR t0[64] = {0};
            if (remote_item_text(tree, cur, t0, 64) && ci_eq(t0, L"Z:")) {
                fprintf(stderr, "pdgdrive: bypassing folder-not-loaded case\n");
                return 2;
            }
        }
        if (!next) {
            fprintf(stderr, "pdgdrive: tree component not found: ");
            /* comp is WCHAR*; log via utf8 */
            int n8 = WideCharToMultiByte(CP_UTF8, 0, comp, -1, NULL, 0, NULL, NULL);
            char *b8 = (char *)malloc((size_t)n8 + 1);
            WideCharToMultiByte(CP_UTF8, 0, comp, -1, b8, n8, NULL, NULL);
            fprintf(stderr, "%s\n", b8);
            free(b8);
            return 0;
        }
        if (cur) SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)cur);
        Sleep(200);
        SendMessageW(tree, TVM_SELECTITEM, TVGN_CARET, (LPARAM)next);
        Sleep(200);
        cur = next;
    }
    return 1;
}


/* Desktop-rooted pick: the deployer plants a symlink on the Wine desktop
 * (see worker); we only need to expand the root and select that child. */
static int pick_named_child(HWND tree, const WCHAR *child) {
    HTREEITEM desk = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0);
    if (!desk) return 0;
    SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)desk);
    Sleep(1500);
    HTREEITEM it = find_child_by_text(tree, desk, child);
    if (!it) return 0;
    SendMessageW(tree, TVM_SELECTITEM, TVGN_CARET, (LPARAM)it);
    Sleep(300);
    return 1;
}


/* Pre-seed Pdg2Pic.ini next to the executable. UTF-16LE with BOM,
 * [ParaBlock] section, exactly like the app writes it. */
static int write_ini(const WCHAR *ini_path, const WCHAR *src_win,
                     const WCHAR *pdf_win) {
    FILE *f = NULL;
    _wfopen_s(&f, ini_path, L"wb");
    if (!f) return 0;
    static const BYTE bom[] = {0xFF, 0xFE};
    fwrite(bom, 1, sizeof(bom), f);
    fwprintf(f, L"[ParaBlock]\r\n");
    fwprintf(f, L"PARA_DIR_SRC=%s\r\n", src_win);
    fwprintf(f, L"PARA_DIR_TGT=%s\r\n", pdf_win);
    fwprintf(f, L"PARA_TGT_TYPE=1\r\n");   /* 1 = PDF file target */
    fwprintf(f, L"PARA_TGT_AS_SRC=0\r\n");
    fclose(f);
    return 1;
}

static int find_pdf(const WCHAR *watch, WCHAR *out, size_t cap) {
    WCHAR pat[MAX_PATH];
    _snwprintf(pat, MAX_PATH - 1, L"%s\\*.pdf", watch);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    int found = 0;
    FILETIME best = {0, 0};
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        if (CompareFileTime(&fd.ftLastWriteTime, &best) > 0) {
            best = fd.ftLastWriteTime;
            _snwprintf(out, cap - 1, L"%s\\%s", watch, fd.cFileName);
            found = 1;
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return found;
}

static long file_size(const WCHAR *path) {
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL,
                           OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return -1;
    DWORD hi = 0;
    DWORD lo = GetFileSize(h, &hi);
    CloseHandle(h);
    if (lo == INVALID_FILE_SIZE && hi == 0) return -1;
    return (long)lo;
}

static int contains_any(const WCHAR *hay, const WCHAR *const *needles, int n) {
    for (int i = 0; i < n; i++)
        if (wcsstr(hay, needles[i])) return 1;
    return 0;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmdline, int show) {
    (void)inst; (void)prev; (void)cmdline; (void)show;
    WCHAR *cl = GetCommandLineW();
    WCHAR src[MAX_PATH] = {0}, pdf[MAX_PATH] = {0}, app[MAX_PATH] = {0};
    WCHAR desk_name[MAX_PATH] = {0};
    int timeout_sec = 1800;

    {
        int argc = 0;
        LPWSTR *argv = CommandLineToArgvW(cl, &argc);
        if (!argv) { fprintf(stderr, "pdgdrive: argv parse failed\n"); return 2; }
        for (int i = 1; i < argc; i++) {
            if (!wcscmp(argv[i], L"--src") && i + 1 < argc)
                wcsncpy(src, argv[++i], MAX_PATH - 1);
            else if (!wcscmp(argv[i], L"--pdf") && i + 1 < argc)
                wcsncpy(pdf, argv[++i], MAX_PATH - 1);
            else if (!wcscmp(argv[i], L"--app") && i + 1 < argc)
                wcsncpy(app, argv[++i], MAX_PATH - 1);
            else if (!wcscmp(argv[i], L"--name") && i + 1 < argc)
                wcsncpy(desk_name, argv[++i], MAX_PATH - 1);
            else if (!wcscmp(argv[i], L"--timeout") && i + 1 < argc)
                timeout_sec = _wtoi(argv[++i]);
        }
        LocalFree(argv);
    }
    if (!src[0] || !pdf[0]) {
        fprintf(stderr, "usage: pdgdrive.exe --src <dir> --pdf <out.pdf> "
                        "[--timeout <sec>] [--app Pdg2Pic.exe]\n");
        return 2;
    }
    WCHAR src_win[MAX_PATH] = {0}, pdf_win[MAX_PATH] = {0};
    unix_to_win(src, src_win, MAX_PATH);
    unix_to_win(pdf, pdf_win, MAX_PATH);
    /* watch the PDF's directory */
    wcsncpy(g_watch_dir, pdf_win, MAX_PATH - 1);
    WCHAR *bs = wcsrchr(g_watch_dir, L'\\');
    if (bs) *bs = 0;
    fprintf(stderr, "pdgdrive: src=%ls\npdgdrive: pdf=%ls\n", src_win, pdf_win);

    /* locate / verify the app next to us */
    if (!app[0]) {
        WCHAR dir[MAX_PATH] = {0};
        GetModuleFileNameW(NULL, dir, MAX_PATH - 1);
        WCHAR *b = wcsrchr(dir, L'\\');
        if (b) *b = 0;
        _snwprintf(app, MAX_PATH - 1, L"%s\\Pdg2Pic.exe", dir);
    }
    {
        HANDLE f = CreateFileW(app, GENERIC_READ, FILE_SHARE_READ, NULL,
                               OPEN_EXISTING, 0, NULL);
        if (f == INVALID_HANDLE_VALUE) {
            fprintf(stderr, "pdgdrive: app not found: "); utf8_print(stderr, app);
            return 2;
        }
        CloseHandle(f);
    }

    if (FAILED(CoInitialize(NULL))) {
        fprintf(stderr, "pdgdrive: CoInitialize failed\n");
        return 2;
    }

    /* pre-seed the ini next to the app */
    {
        WCHAR ini[MAX_PATH] = {0}, dir[MAX_PATH] = {0};
        wcsncpy(dir, app, MAX_PATH - 1);
        WCHAR *b = wcsrchr(dir, L'\\');
        if (b) *b = 0;
        _snwprintf(ini, MAX_PATH - 1, L"%s\\Pdg2Pic.ini", dir);
        if (!write_ini(ini, src_win, pdf_win)) {
            fprintf(stderr, "pdgdrive: cannot write ini\n");
            return 2;
        }
    }

    /* launch the app (visible; hidden windows block its modal dialogs) */
    {
        STARTUPINFOW si = {0};
        si.cb = sizeof(si);
        si.wShowWindow = SW_SHOW;
        si.dwFlags = STARTF_USESHOWWINDOW;
        WCHAR cmdbuf[MAX_PATH + 8] = {0};
        _snwprintf(cmdbuf, MAX_PATH + 7, L"\"%s\"", app);
        if (!CreateProcessW(app, cmdbuf, NULL, NULL, FALSE, 0, NULL, NULL,
                            &si, &g_pi)) {
            fprintf(stderr, "pdgdrive: CreateProcess failed %lu\n",
                    GetLastError());
            return 2;
        }
    }

    /* find the main window */
    for (int i = 0; i < 60 && !g_main; i++) {
        EnumWindows(main_enum, 0);
        if (!g_main) Sleep(500);
    }
    if (!g_main) {
        fprintf(stderr, "pdgdrive: main window not found; windows:\n");
        EnumWindows(dbg_dump, 0);
        kill_app();
        return 3;
    }
    fprintf(stderr, "pdgdrive: main window %lx\n", (unsigned long)g_main);

    /* feed the source folder through the app's folder picker:
     * click the browse button, walk the picker tree to our desktop
     * folder (--name), and confirm with OK. */
    Sleep(1500);
    HWND list = GetDlgItem(g_main, FILE_LIST_ID);
    {
        HWND browse = GetDlgItem(g_main, SRC_BROWSE_ID);
        if (!browse) { fprintf(stderr, "pdgdrive: browse button missing\n"); kill_app(); return 3; }
        SendMessageTimeoutW(browse, BM_CLICK, 0, 0, SMTO_ABORTIFHUNG, 5000, NULL);

        HWND picker = NULL, ped = NULL;
        for (int i = 0; i < 80 && !ped; i++) {
            Sleep(500);
            for (HWND h = FindWindowExW(NULL, NULL, L"#32770", NULL); h;
                 h = FindWindowExW(NULL, h, L"#32770", NULL)) {
                DWORD p = 0; GetWindowThreadProcessId(h, &p);
                if (p != g_app_pid || h == g_main) continue;
                if (!IsWindowVisible(h)) continue;
                WCHAR t[128] = {0};
                GetWindowTextW(h, t, 127);
                if (wcsstr(t, L"Pdg2Pic")) continue;
                struct find_ctx2 tc = { 0, NULL };
                EnumChildWindows(h, find_by_class_tree, (LPARAM)&tc);
                if (!tc.found) continue;
                HWND e = find_first_edit(h);
                if (!e) continue;
                picker = h; ped = e;
                break;
            }
        }
        if (!picker) { fprintf(stderr, "pdgdrive: folder picker did not open\n"); kill_app(); return 3; }
        fprintf(stderr, "pdgdrive: picker %lx\n", (unsigned long)picker);

        struct find_ctx2 tc = { 0, NULL };
        EnumChildWindows(picker, find_by_class_tree, (LPARAM)&tc);
        HWND tree = tc.found;
        HWND okbtn = find_ctrl(picker, PICKER_OK_ID);
        g_app_proc = OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_READ |
                                     PROCESS_VM_WRITE, FALSE, g_app_pid);
        if (!g_app_proc) { fprintf(stderr, "pdgdrive: OpenProcess failed\n"); kill_app(); return 3; }
        int picked = 0;
        if (desk_name[0] && tree)
            picked = pick_named_child(tree, desk_name);
        else if (tree)
            picked = pick_path_in_tree(tree, src_win);
        fprintf(stderr, "pdgdrive: tree pick=%d ok enabled=%d\n",
                picked, okbtn ? IsWindowEnabled(okbtn) : -1);
        for (int i = 0; i < 30 && okbtn && !IsWindowEnabled(okbtn); i++) Sleep(300);
        if (!okbtn) okbtn = find_ctrl(picker, PICKER_OK_ID);
        if (!okbtn) { fprintf(stderr, "pdgdrive: picker OK missing\n"); kill_app(); return 3; }
        SendMessageW(picker, WM_COMMAND, MAKEWPARAM(IDOK, BN_CLICKED), (LPARAM)okbtn);
        Sleep(1500);
    }
    {
        WCHAR a[512] = {0}, b[512] = {0};
        GetDlgItemTextW(g_main, 1066, a, 511);
        GetDlgItemTextW(g_main, 1064, b, 511);
        fprintf(stderr, "pdgdrive: edit1066: "); utf8_print(stderr, a);
        fprintf(stderr, "pdgdrive: edit1064: "); utf8_print(stderr, b);
        fprintf(stderr, "pdgdrive: list items=%ld\n",
                list ? (long)SendMessageW(list, LVM_GETITEMCOUNT, 0, 0) : -1);
    }

    /* start conversion (the on-screen "4" button); retry a few times */
    HWND btn = GetDlgItem(g_main, START_BTN_ID);
    if (!btn) { fprintf(stderr, "pdgdrive: start button missing\n"); kill_app(); return 3; }
    for (int a = 0; a < 5; a++) {
        fprintf(stderr, "pdgdrive: start attempt %d enabled=%d\n",
                a, IsWindowEnabled(btn));
        SendMessageTimeoutW(btn, BM_CLICK, 0, 0, SMTO_ABORTIFHUNG, 5000, NULL);
        Sleep(5000);
    }

    /* wait for the PDF; handle popups */
    DWORD start = GetTickCount();
    WCHAR found[MAX_PATH] = {0};
    long last_size = -1; int stable = 0;
    while ((GetTickCount() - start) / 1000 < (DWORD)timeout_sec) {
        struct popup_info pi = {0};
        EnumWindows(popup_enum, (LPARAM)&pi);
        if (pi.hwnd) {
            int is_done = wcsstr(pi.text, TXT_OK_DONE) != NULL;
            int is_err = contains_any(pi.text,
                (const WCHAR *const[]){TXT_ERR1, TXT_ERR2, TXT_ERR3, TXT_ERR4}, 4);
            fprintf(stderr, "pdgdrive: popup: "); utf8_print(stderr, pi.text);
            SendMessageW(pi.hwnd, WM_CLOSE, 0, 0);
            Sleep(300);
            if (is_err && !is_done) { kill_app(); return 6; }
        }
        if (find_pdf(g_watch_dir, found, MAX_PATH)) {
            long sz = file_size(found);
            if (sz >= 0 && sz == last_size) {
                if (++stable >= 3) {
                    fprintf(stdout, "PDF="); utf8_print(stdout, found);
                    kill_app();
                    return 0;
                }
            } else {
                stable = 0; last_size = sz;
            }
        }
        Sleep(1000);
    }
    fprintf(stderr, "pdgdrive: timeout\n");
    kill_app();
    return 5;
}
