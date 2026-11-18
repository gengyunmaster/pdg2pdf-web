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

#define SRC_EDIT_ID   1066   /* 0x42a  source folder edit            */
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

static BOOL CALLBACK main_enum(HWND hwnd, LPARAM lp) {
    WCHAR cls[64] = {0}, title[256] = {0};
    (void)lp;
    GetClassNameW(hwnd, cls, 63);
    GetWindowTextW(hwnd, title, 255);
    if (wcscmp(cls, L"#32770") == 0 && wcscmp(title, L"Pdg2Pic") == 0) {
        g_main = hwnd;
        GetWindowThreadProcessId(hwnd, &g_app_pid);
        return FALSE;
    }
    return TRUE;
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
        si.wShowWindow = SW_HIDE;
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
    if (!g_main) { fprintf(stderr, "pdgdrive: main window not found\n"); kill_app(); return 3; }
    fprintf(stderr, "pdgdrive: main window %lx\n", (unsigned long)g_main);

    /* 2. set the source folder; EN_CHANGE fires the app's scan handler */
    if (!SetDlgItemTextW(g_main, SRC_EDIT_ID, src)) {
        fprintf(stderr, "pdgdrive: SetDlgItemText(1066) failed %lu\n",
                GetLastError());
        kill_app(); return 3;
    }
    Sleep(1500); /* allow the scan to populate the list */

    /* 3. confirm the list got items (LVM_GETITEMCOUNT) */
    HWND list = GetDlgItem(g_main, FILE_LIST_ID);
    int items = (int)SendMessageW(list, LVM_GETITEMCOUNT, 0, 0);
    fprintf(stderr, "pdgdrive: file list items=%d\n", items);

    /* 4. start conversion (ID 1 = the on-screen "4" step button) */
    HWND btn = GetDlgItem(g_main, START_BTN_ID);
    if (!btn) { fprintf(stderr, "pdgdrive: start button missing\n"); kill_app(); return 3; }
    SendMessageW(btn, BM_CLICK, 0, 0);

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
