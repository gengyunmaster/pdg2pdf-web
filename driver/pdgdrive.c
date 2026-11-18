// pdgdrive.c — Win32 message-level driver for Pdg2Pic.exe (Phase A).
//
// Runs next to Pdg2Pic.exe under the same Wine prefix. Automates the main
// dialog with Win32 messages only — no coordinates, no keystrokes:
//
//   1. Launch Pdg2Pic.exe from the driver's own directory (hidden window —
//      a headless run needs no rendering), unless --app says otherwise.
//   2. Find the main dialog (class #32770, title "Pdg2Pic").
//   3. Set the source-folder edit control (ID 1066 / 0x42a) with
//      SetDlgItemTextW and let the app's EN_CHANGE handler scan the folder.
//   4. Confirm the file list (SysListView32, ID 1006 / 0x3ee) got items.
//   5. Click the start-conversion button (ID 1 = IDOK, "&4 ..." per the
//      on-screen 1/2/3/4 step buttons and the documented shortcut key "4").
//   6. Watch for the output PDF (stable size) and for modal popups owned by
//      the app; read popup text, classify, close them.
//
// Control IDs were confirmed live with windowdump.exe under Wine
// (scripts/recon.sh). Exit codes: see usage below.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <commctrl.h>

/* DROPFILES is ABI-stable; declare it locally to avoid header-guard
 * differences across mingw-w64 versions. */
typedef struct {
    DWORD pFiles;
    POINT pt;
    BOOL  fNC;
    BOOL  fWide;
} DRV_DROPFILES;   /* DROPFILES for WM_DROPFILES */

#define SRC_EDIT_ID     1066 /* 0x42a  source folder edit                */
#define SRC_BROWSE_ID   1004 /* 0x3ec  opens the source folder picker     */
#define PICKER_EDIT_ID  3745 /* 0xea1  folder-name edit in the picker     */
#define PICKER_OK_ID       1 /*        picker's OK button                 */
#define FILE_LIST_ID  1006   /* 0x3ee  SysListView32                 */
#define START_BTN_ID  1      /* IDOK, labeled "4 ..." = start        */

/* Chinese text in \uXXXX escapes so the source stays encoding-agnostic. */
static const WCHAR TXT_OK_DONE[] =
    {0x8f6c,0x6362,0x5b8c,0x6bd5,0};                    /* 转换完毕 */
static const WCHAR TXT_ERR1[] = {0x9519,0x8bef,0};      /* 错误 */
static const WCHAR TXT_ERR2[] = {0x5931,0x8d25,0};      /* 失败 */
static const WCHAR TXT_ERR3[] = {0x62b1,0x6b49,0};      /* 抱歉 */
static const WCHAR TXT_ERR4[] = {0x6ca1,0x6709,0};      /* 没有 */

static DWORD g_app_pid = 0;
static HWND  g_main = NULL;
static PROCESS_INFORMATION g_pi = {0};
static WCHAR g_watch_win[MAX_PATH] = {0};
static HANDLE g_app_proc = NULL;

static void kill_app(void) {
    if (g_pi.hProcess) {
        TerminateProcess(g_pi.hProcess, 0);
        WaitForSingleObject(g_pi.hProcess, 3000);
        CloseHandle(g_pi.hProcess);
        CloseHandle(g_pi.hThread);
        g_pi.hProcess = NULL;
    }
}

struct popup_info {
    HWND hwnd;
    WCHAR text[1024];
};


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

static BOOL CALLBACK popup_enum(HWND hwnd, LPARAM lp) {
    struct popup_info *pi = (struct popup_info *)lp;
    WCHAR cls[64] = {0};
    DWORD pid = 0;
    GetClassNameW(hwnd, cls, 63);
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid == g_app_pid && hwnd != g_main && wcscmp(cls, L"#32770") == 0) {
        /* first owned dialog window wins */
        dump_popup_text(hwnd, pi->text, sizeof(pi->text) / sizeof(WCHAR));
        pi->hwnd = hwnd;
        return FALSE;
    }
    return TRUE;
}


static BOOL CALLBACK dbg_dump(HWND hwnd, LPARAM lp) {
    (void)lp;
    WCHAR cls[64] = {0}, title[256] = {0};
    DWORD pid = 0;
    GetClassNameW(hwnd, cls, 63);
    GetWindowTextW(hwnd, title, 255);
    GetWindowThreadProcessId(hwnd, &pid);
    fprintf(stderr, "  win pid=%lu cls=", pid);
    utf8_print(stderr, cls);
    fprintf(stderr, " title=");
    utf8_print(stderr, title);
    return TRUE;
}



/* Wine exposes the container filesystem under drive Z:. Convert a Unix
 * path (/srv/data/x) to what a Windows program understands (Z:\srv\data\x). */
static void unix_to_win(const WCHAR *in, WCHAR *out, size_t cap) {
    size_t o = 0;
    if (in[0] == L'/' && cap > 4) {
        out[o++] = L'Z'; out[o++] = L':';
    }
    for (size_t i = 0; in[i] && o + 1 < cap; i++) {
        WCHAR c = in[i];
        out[o++] = (c == L'/') ? L'\\' : c;
    }
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

static int find_pdf(const WCHAR *watch, WCHAR *out, size_t cap) {
    WCHAR pat[MAX_PATH];
    _snwprintf(pat, MAX_PATH - 1, L"%s\\*.pdf", g_watch_win);
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
    WCHAR src[MAX_PATH] = {0}, watch[MAX_PATH] = {0}, app[MAX_PATH] = {0};
    int timeout_sec = 1800;

    /* arg parse: --src <dir> --watch <dir> [--timeout N] [--app exe] */
    {
        int argc = 0;
        LPWSTR *argv = CommandLineToArgvW(cl, &argc);
        if (!argv) { fprintf(stderr, "pdgdrive: argv parse failed\n"); return 2; }
        for (int i = 1; i < argc; i++) {
            if (!wcscmp(argv[i], L"--src") && i + 1 < argc)
                wcsncpy(src, argv[++i], MAX_PATH - 1);
            else if (!wcscmp(argv[i], L"--watch") && i + 1 < argc)
                wcsncpy(watch, argv[++i], MAX_PATH - 1);
            else if (!wcscmp(argv[i], L"--app") && i + 1 < argc)
                wcsncpy(app, argv[++i], MAX_PATH - 1);
            else if (!wcscmp(argv[i], L"--timeout") && i + 1 < argc)
                timeout_sec = _wtoi(argv[++i]);
        }
        LocalFree(argv);
    }
    if (!src[0] || !watch[0]) {
        fprintf(stderr, "usage: pdgdrive.exe --src <dir> --watch <dir> "
                        "[--timeout <sec>] [--app Pdg2Pic.exe]\n");
        return 2;
    }
    WCHAR src_win[MAX_PATH] = {0};
    unix_to_win(src, src_win, MAX_PATH);
    unix_to_win(watch, g_watch_win, MAX_PATH);
    fprintf(stderr, "pdgdrive: src=%ls watch=%ls\n", src_win, g_watch_win);

    /* 0. launch Pdg2Pic.exe (hidden) from the driver's own directory */
    if (!app[0]) {
        WCHAR dir[MAX_PATH] = {0};
        GetModuleFileNameW(NULL, dir, MAX_PATH - 1);
        WCHAR *bs = wcsrchr(dir, L'\\');
        if (bs) *bs = 0;
        _snwprintf(app, MAX_PATH - 1, L"%s\\Pdg2Pic.exe", dir);
    }
    {
        WCHAR probe[MAX_PATH] = {0};
        if (GetFullPathNameW(app, MAX_PATH, probe, NULL) == 0) {
            fprintf(stderr, "pdgdrive: cannot resolve app path\n");
            return 2;
        }
        HANDLE f = CreateFileW(probe, GENERIC_READ, FILE_SHARE_READ, NULL,
                               OPEN_EXISTING, 0, NULL);
        if (f == INVALID_HANDLE_VALUE) {
            fprintf(stderr, "pdgdrive: app not found: "); utf8_print(stderr, probe); fprintf(stderr, "\n");
            return 2;
        }
        CloseHandle(f);

        STARTUPINFOW si = {0};
        si.cb = sizeof(si);
        si.wShowWindow = SW_SHOW;
        si.dwFlags = STARTF_USESHOWWINDOW;
        WCHAR cmdbuf[MAX_PATH + 8] = {0};
        _snwprintf(cmdbuf, MAX_PATH + 7, L"\"%s\"", probe);
        if (!CreateProcessW(probe, cmdbuf, NULL, NULL, FALSE, 0, NULL, NULL,
                            &si, &g_pi)) {
            fprintf(stderr, "pdgdrive: CreateProcess failed %lu\n",
                    GetLastError());
            return 2;
        }
    }

    /* 1. locate the main window (retry: the app may still be starting) */
    for (int i = 0; i < 60 && !g_main; i++) {
        EnumWindows(main_enum, 0);
        if (!g_main) Sleep(500);
    }
    if (!g_main) {
        fprintf(stderr, "pdgdrive: main window not found; visible top-level windows:\n");
        EnumWindows(dbg_dump, 0);
        kill_app(); return 3;
    }
    fprintf(stderr, "pdgdrive: main window %lx\n", (unsigned long)g_main);

    /* 2. open the source folder picker and submit our path */
    HWND browse = GetDlgItem(g_main, SRC_BROWSE_ID);
    if (!browse) { fprintf(stderr, "pdgdrive: browse button missing\n"); kill_app(); return 3; }
    fprintf(stderr, "pdgdrive: browse hwnd=%lx\n", (unsigned long)browse);
    SendMessageTimeoutW(browse, BM_CLICK, 0, 0, SMTO_ABORTIFHUNG, 5000, NULL);

    /* wait for the picker: a #32770 owned by the app, not the main window,
     * actually containing the folder-name edit (control 3745) */
    HWND picker = NULL, ped = NULL;
    for (int i = 0; i < 80 && !ped; i++) {
        Sleep(500);
        for (HWND h = FindWindowExW(NULL, NULL, L"#32770", NULL); h;
             h = FindWindowExW(NULL, h, L"#32770", NULL)) {
            DWORD p = 0; GetWindowThreadProcessId(h, &p);
            if (p != g_app_pid || h == g_main) continue;
            if (!IsWindowVisible(h)) continue;   /* skip childless shadows */
            WCHAR t[128] = {0};
            GetWindowTextW(h, t, 127);
            if (wcsstr(t, L"Pdg2Pic")) continue; /* not the picker */
            /* a folder picker has a tree; a save dialog does not */
            if (!find_ctrl(h, 0 /*never*/)) { }
            struct find_ctx2 tc = { 0, NULL };
            EnumChildWindows(h, find_by_class_tree, (LPARAM)&tc);
            if (!tc.found) continue;
            HWND e = find_first_edit(h);
            if (!e) continue;
            picker = h; ped = e;
            fprintf(stderr, "pdgdrive: candidate dialog %lx title=", (unsigned long)h);
            utf8_print(stderr, t);
            break;
        }
    }
    if (!picker) {
        fprintf(stderr, "pdgdrive: folder picker did not open; state dump:\n");
        EnumWindows(dbg_dump, 0);
        for (HWND h = FindWindowExW(NULL, NULL, L"#32770", NULL); h;
             h = FindWindowExW(NULL, h, L"#32770", NULL)) {
            DWORD p = 0; GetWindowThreadProcessId(h, &p);
            if (p != g_app_pid) continue;
            fprintf(stderr, "-- dialog %lx children:\n", (unsigned long)h);
            EnumChildWindows(h, dbg_dump, 0);
        }
        kill_app(); return 3;
    }
    fprintf(stderr, "pdgdrive: picker %lx\n", (unsigned long)picker);
    SetWindowTextW(ped, src_win);  /* cosmetic only */
    /* probe tree state */
    HWND tree = NULL;
    struct find_ctx2 tc = { 0, NULL };
    EnumChildWindows(picker, find_by_class_tree, (LPARAM)&tc);
    tree = tc.found;
    HWND ok0 = find_ctrl(picker, PICKER_OK_ID);
    fprintf(stderr, "pdgdrive: tree=%lx count=%ld ok=%lx enabled=%d\n",
            (unsigned long)tree,
            tree ? (long)SendMessageW(tree, TVM_GETCOUNT, 0, 0) : -1,
            (unsigned long)ok0, ok0 && IsWindowEnabled(ok0));
    /* select our folder via cross-process tree walking */
    g_app_proc = OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_READ |
                                 PROCESS_VM_WRITE,
                             FALSE, g_app_pid);
    if (!g_app_proc) {
        fprintf(stderr, "pdgdrive: OpenProcess failed %lu\n", GetLastError());
        kill_app(); return 3;
    }
    {
        HTREEITEM lvl[3] = { NULL, NULL, NULL };
        lvl[0] = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0);
        for (int d = 0; d < 3 && lvl[d]; d++) {
            HTREEITEM it = lvl[d];
            while (it) {
                WCHAR t[256] = {0};
                if (remote_item_text(tree, it, t, 256)) {
                    fprintf(stderr, "pdgdrive: L%d item: ", d); utf8_print(stderr, t);
                }
                it = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, (LPARAM)it);
            }
            if (d < 2) {
                SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)lvl[d]);
                Sleep(800);
                lvl[d + 1] = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM,
                                                     TVGN_CHILD, (LPARAM)lvl[d]);
            }
        }
    }
    int picked = tree ? pick_path_in_tree(tree, src_win) : 0;
    fprintf(stderr, "pdgdrive: tree pick=%d ok_enabled=%d\n",
            picked, ok0 ? IsWindowEnabled(ok0) : -1);
    if (picked == 2) {
        WCHAR zb[] = {L'Z', L':', L'\', 0};
        SendMessageW(picker, WM_USER + 102, TRUE, (LPARAM)zb);
        Sleep(2500);
        fprintf(stderr, "pdgdrive: BFFM(Z:\\) ok_enabled=%d\n",
                ok0 ? IsWindowEnabled(ok0) : -1);
    }
    for (int i = 0; i < 30 && ok0 && !IsWindowEnabled(ok0); i++) Sleep(300);
    fprintf(stderr, "pdgdrive: before OK, enabled=%d\n",
            ok0 ? IsWindowEnabled(ok0) : -1);
    HWND ok = find_ctrl(picker, PICKER_OK_ID);
    if (!ok) { fprintf(stderr, "pdgdrive: picker OK missing\n"); kill_app(); return 3; }
    SendMessageTimeoutW(ok, BM_CLICK, 0, 0, SMTO_ABORTIFHUNG, 5000, NULL);
    Sleep(1000);
    WCHAR after[512] = {0};
    GetDlgItemTextW(g_main, SRC_EDIT_ID, after, 511);
    fprintf(stderr, "pdgdrive: source edit after picker: "); utf8_print(stderr, after);
    if (IsWindow(picker)) fprintf(stderr, "pdgdrive: WARN picker still open\n");

    /* 3. observe the list (informational; conversion may not need it) */
    HWND list = GetDlgItem(g_main, FILE_LIST_ID);
    int items = 0;
    for (int i = 0; i < 60; i++) {
        items = (int)SendMessageW(list, LVM_GETITEMCOUNT, 0, 0);
        if (items > 0) break;
        Sleep(500);
    }
    fprintf(stderr, "pdgdrive: file list items=%d\n", items);

    /* 4. make sure the source edit carries our path, then start */
    SetDlgItemTextW(g_main, SRC_EDIT_ID, src_win);
    HWND edit2 = GetDlgItem(g_main, SRC_EDIT_ID);
    SendMessageW(g_main, WM_COMMAND,
                 MAKEWPARAM(SRC_EDIT_ID, EN_KILLFOCUS), (LPARAM)edit2);
    Sleep(500);
    HWND btn = GetDlgItem(g_main, START_BTN_ID);
    if (!btn) { fprintf(stderr, "pdgdrive: start button missing\n"); kill_app(); return 3; }
    fprintf(stderr, "pdgdrive: clicking start (hwnd=%lx)\n", (unsigned long)btn);
    SendMessageTimeoutW(btn, BM_CLICK, 0, 0, SMTO_ABORTIFHUNG, 5000, NULL);

    /* 5. wait for the PDF; handle popups */
    DWORD start = GetTickCount();
    WCHAR pdf[MAX_PATH] = {0};
    long last_size = -1; int stable = 0;
    while ((GetTickCount() - start) / 1000 < (DWORD)timeout_sec) {
        struct popup_info pi = {0};
        EnumWindows(popup_enum, (LPARAM)&pi);
        if (pi.hwnd) {
            int is_done = wcsstr(pi.text, TXT_OK_DONE) != NULL;
            int is_err = contains_any(pi.text,
                (const WCHAR *const[]){TXT_ERR1, TXT_ERR2, TXT_ERR3, TXT_ERR4}, 4);
            fprintf(stderr, "pdgdrive: popup: "); utf8_print(stderr, pi.text); fprintf(stderr, "\n");
            /* completion prompts and error boxes both get closed */
            SendMessageW(pi.hwnd, WM_CLOSE, 0, 0);
            Sleep(300);
            if (is_err && !is_done) {
                fprintf(stderr, "pdgdrive: fatal popup, aborting\n");
                kill_app(); return 6;
            }
        }
        if (find_pdf(watch, pdf, MAX_PATH)) {
            long sz = file_size(pdf);
            if (sz >= 0 && sz == last_size) {
                if (++stable >= 3) {
                    fprintf(stdout, "PDF="); utf8_print(stdout, pdf);
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
    kill_app(); return 5;
}
