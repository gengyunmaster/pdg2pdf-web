# Driver: pdgdrive.exe

`pdgdrive.exe` is a tiny Win32 program that drives `Pdg2Pic.exe` by messages.
It runs under the **same Wine prefix** as Pdg2Pic, so plain Win32 APIs work
against the real windows — Wine implements them faithfully, which is why
message-level automation is preferred over any coordinate-based tool.

## Planned message flow (implemented and verified in Phase A)

1. **Locate**: `FindWindow(NULL, L"Pdg2Pic")` — fall back to enumerating
   top-level windows and matching the title prefix.
2. **Configure**: conversion settings are written to `Pdg2Pic.ini` before
   launch (exact key layout is confirmed empirically by diffing an ini file
   the application itself generates).
3. **Input**: set the source-folder edit control (`FindWindowEx` +
   `WM_SETTEXT`), or post a synthetic `WM_DROPFILES`: allocate a
   `DROPFILES` structure (+ path list) with `GlobalAlloc(GMEM_SHARE)` and
   `PostMessage(hwnd, WM_DROPFILES, hGlobal, 0)`. Drag-and-drop is the most
   stable input path because it is a documented feature of the app.
4. **Start**: `BM_CLICK`/`BM_SETSTATE` on the start-conversion button, or
   `PostMessage(WM_COMMAND, idOfButton)` once the control ID is confirmed.
5. **Wait**: poll for the output PDF and/or the `Pdg2Pic_log.txt` marker;
   enforce a timeout; kill the Wine process tree on hang (MODI is not used
   in this pipeline, but defensive cleanup stays).
6. **Report**: exit code 0 + path on success; non-zero + stderr message.

## Build (cross-compile, no Windows machine needed)

```bash
sudo apt install gcc-mingw-w64-i686
make            # or: i686-w64-mingw32-gcc -O2 -mwindows pdgdrive.c -o pdgdrive.exe
```

The Dockerfile builds it automatically at image build time.

## Verifying the dialog layout

Tools: `wine` + `xwininfo -root -tree` under Xvfb to list window/class names,
or a one-off `EnumWindows` dump build of this driver. Control IDs are read
with `GetDlgCtrlID` from a debug build, never guessed.
