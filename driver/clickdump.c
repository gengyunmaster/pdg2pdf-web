// clickdump.c — dev probe: click a control on the Pdg2Pic main window and
// dump the resulting window state. Usage: clickdump.exe <control-id>
#include <stdio.h>
#include <string.h>
#include <windows.h>

static DWORD g_pid = 0;
static HWND g_main = NULL;

static void dump_one(HWND hwnd) {
    WCHAR cls[256] = {0}, title[1024] = {0};
    DWORD pid = 0;
    GetClassNameW(hwnd, cls, 255);
    GetWindowTextW(hwnd, title, 1023);
    GetWindowThreadProcessId(hwnd, &pid);
    RECT rc; GetWindowRect(hwnd, &rc);
    printf("hwnd=%08lx id=%04x vis=%d area=%ld cls=%-24s title=%ls pid=%lu\n",
           (unsigned long)hwnd, (unsigned)GetDlgCtrlID(hwnd),
           IsWindowVisible(hwnd) ? 1 : 0,
           (long)((rc.right - rc.left) * (rc.bottom - rc.top)),
           cls, title, pid);
}

static BOOL CALLBACK main_enum(HWND hwnd, LPARAM lp) {
    WCHAR cls[64] = {0}, title[256] = {0};
    (void)lp;
    GetClassNameW(hwnd, cls, 63);
    GetWindowTextW(hwnd, title, 255);
    if (!wcscmp(cls, L"#32770") && !wcscmp(title, L"Pdg2Pic") &&
        FindWindowExW(hwnd, NULL, L"SysListView32", NULL)) {
        g_main = hwnd;
        GetWindowThreadProcessId(hwnd, &g_pid);
        return FALSE;
    }
    return TRUE;
}

static BOOL CALLBACK child_all(HWND hwnd, LPARAM lp) {
    (void)lp;
    dump_one(hwnd);
    return TRUE;
}

static BOOL CALLBACK top_all(HWND hwnd, LPARAM lp) {
    (void)lp;
    dump_one(hwnd);
    return TRUE;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmdline, int show) {
    (void)inst; (void)prev; (void)show;
    int id = cmdline ? atoi(cmdline) : 0;
    if (id <= 0) { fprintf(stderr, "usage: clickdump.exe <control-id>\n"); return 2; }

    for (int i = 0; i < 60 && !g_main; i++) { EnumWindows(main_enum, 0); if (!g_main) Sleep(500); }
    if (!g_main) { fprintf(stderr, "no main\n"); return 3; }

    HWND btn = GetDlgItem(g_main, id);
    printf("clicking id=%d -> hwnd=%lx\n", id, (unsigned long)btn);
    if (!btn) { printf("no such control\n"); return 4; }
    SendMessageTimeoutW(btn, BM_CLICK, 0, 0, SMTO_ABORTIFHUNG, 5000, NULL);
    Sleep(2500);
    printf("--- top-level after click ---\n");
    EnumWindows(top_all, 0);
    printf("--- children of main after click ---\n");
    EnumChildWindows(g_main, child_all, 0);
    printf("--- other same-pid dialogs ---\n");
    struct enum2 { DWORD pid; HWND main; };
    (void)0;
    /* dump children of every other #32770 owned by the app */
    HWND top[64]; int n = 0;
    for (HWND h = FindWindowExW(NULL, NULL, L"#32770", NULL); h && n < 64;
         h = FindWindowExW(NULL, h, L"#32770", NULL)) {
        DWORD p = 0; GetWindowThreadProcessId(h, &p);
        if (p == g_pid && h != g_main) top[n++] = h;
    }
    for (int i = 0; i < n; i++) {
        dump_one(top[i]);
        EnumChildWindows(top[i], child_all, 0);
    }
    return 0;
}
