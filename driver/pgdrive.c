// pdgdrive.c — Win32 message-level driver for Pdg2Pic.exe (Phase A).
//
// Cross-compiled for 32-bit Windows (MinGW) and executed under Wine next to
// Pdg2Pic.exe. It automates the GUI with Win32 messages only — never mouse
// coordinates:
//
//   1. Find the Pdg2Pic main dialog window (by title).
//   2. Feed it the source directory (edit control via WM_SETTEXT, or a
//      synthetic WM_DROPFILES built in shared memory).
//   3. Trigger conversion (BM_CLICK on the start button / equivalent command
//      message) with parameters pre-written to Pdg2Pic.ini.
//   4. Poll for completion (output PDF exists / process exits) and report.
//
// This file is a compilable skeleton; the message flow is implemented and
// verified in Phase A against the real dialog layout. See driver/README.md.

#include <stdio.h>
#include <windows.h>

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmdline, int show) {
    (void)inst; (void)prev; (void)show;
    if (cmdline == NULL || cmdline[0] == '\0') {
        fprintf(stderr,
            "usage: pdgdrive.exe <source_dir> <output_pdf> [options]\n"
            "options (placeholder, finalized in Phase A):\n"
            "  --no-rename\n  --keep-source\n");
        return 2;
    }
    fprintf(stderr, "pdgdrive: message-flow implementation pending (Phase A)\n");
    return 1;
}
