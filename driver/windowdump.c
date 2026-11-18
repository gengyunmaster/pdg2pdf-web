// windowdump.c — reconnaissance tool (development only, not shipped in images).
//
// Under Wine, enumerates top-level windows; with "-c <substring>", locates
// the window whose title matches and dumps its child controls. Output:
// hwnd, class name, title, control ID. This is how the real dialog layout of
// Pdg2Pic is confirmed before pdgdrive.c hard-codes any control IDs.

#include <stdio.h>
#include <string.h>
#include <windows.h>

struct find_ctx {
    const char *needle;
    HWND found;
};

static void dump_one(HWND hwnd) {
    char cls[256] = {0}, title[1024] = {0};
    DWORD pid = 0;
    GetClassNameA(hwnd, cls, sizeof(cls) - 1);
    GetWindowTextA(hwnd, title, sizeof(title) - 1);
    GetWindowThreadProcessId(hwnd, &pid);
    printf("hwnd=%08lx id=%04x cls=%-32s title=%s pid=%lu\n",
           (unsigned long)hwnd, (unsigned)GetDlgCtrlID(hwnd), cls, title, pid);
}

static BOOL CALLBACK find_proc(HWND hwnd, LPARAM lp) {
    struct find_ctx *c = (struct find_ctx *)lp;
    char t[512] = {0};
    if (GetWindowTextA(hwnd, t, sizeof(t) - 1) && strstr(t, c->needle)) {
        c->found = hwnd;
        return FALSE;
    }
    return TRUE;
}

static BOOL CALLBACK child_proc(HWND hwnd, LPARAM lp) {
    (void)lp;
    dump_one(hwnd);
    return TRUE;
}

static BOOL CALLBACK top_proc(HWND hwnd, LPARAM lp) {
    (void)lp;
    dump_one(hwnd);
    return TRUE;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmdline, int show) {
    (void)inst; (void)prev; (void)show;
    if (cmdline && strstr(cmdline, "--close")) {
        struct find_ctx c = { "Pdg2Pic", NULL };
        EnumWindows(find_proc, (LPARAM)&c);
        if (!c.found) { fprintf(stderr, "no main\n"); return 3; }
        PostMessageW(c.found, WM_CLOSE, 0, 0);
        Sleep(4000);
        return 0;
    }
    if (cmdline && strstr(cmdline, "-c")) {
        char needle[256] = {0};
        if (sscanf(strstr(cmdline, "-c") + 2, "%255s", needle) != 1) {
            fprintf(stderr, "usage: windowdump.exe [-c substring]\n");
            return 2;
        }
        struct find_ctx c = { needle, NULL };
        EnumWindows(find_proc, (LPARAM)&c);
        if (!c.found) {
            fprintf(stderr, "windowdump: no window matching '%s'\n", needle);
            return 1;
        }
        printf("matched window:\n");
        dump_one(c.found);
        printf("children:\n");
        EnumChildWindows(c.found, child_proc, 0);
        return 0;
    }
    printf("top-level windows:\n");
    EnumWindows(top_proc, 0);
    return 0;
}
