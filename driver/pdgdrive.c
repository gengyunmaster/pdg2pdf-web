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

#define SRC_EDIT_ID   1066   /* 0x42a  source folder edit                */
#define FILE_LIST_ID  1006   /* 0x3ee  SysListView32                     */
#define START_BTN_ID  1      /* IDOK, the on-screen "4 开始转换" button  */

static DWORD g_app_pid = 0;
static HWND  g_main = NULL;
static PROCESS_INFORMATION g_pi = {0};
static WCHAR g_watch_dir[MAX_PATH] = {0};

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

/* Wine exposes the container filesystem under drive Z:. Convert a Unix
 * path (/srv/data/x) to what a Windows program understands (Z:\srv\data\x). */
static void unix_to_win(const WCHAR *in, WCHAR *out, size_t cap) {
    size_t o = 0;
    if (in[0] == L'/' && cap > 4) { out[o++] = L'Z'; out[o++] = L':'; }
    for (size_t i = 0; in[i] && o + 1 < cap; i++)
        out[o++] = (in[i] == L'/') ? L'\\' : in[i];
    out[o] = 0;
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

    /* sanity: the restored source path should sit in the edit */
    Sleep(1500);
    {
        WCHAR cur[512] = {0};
        GetDlgItemTextW(g_main, SRC_EDIT_ID, cur, 511);
        fprintf(stderr, "pdgdrive: source edit: "); utf8_print(stderr, cur);
        HWND list = GetDlgItem(g_main, FILE_LIST_ID);
        fprintf(stderr, "pdgdrive: list items=%ld\n",
                list ? (long)SendMessageW(list, LVM_GETITEMCOUNT, 0, 0) : -1);
    }

    /* start conversion (the on-screen "4" button) */
    HWND btn = GetDlgItem(g_main, START_BTN_ID);
    if (!btn) { fprintf(stderr, "pdgdrive: start button missing\n"); kill_app(); return 3; }
    SendMessageTimeoutW(btn, BM_CLICK, 0, 0, SMTO_ABORTIFHUNG, 5000, NULL);

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
