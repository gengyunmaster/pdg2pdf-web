CC ?= i686-w64-mingw32-gcc

all: pdgdrive.exe windowdump.exe

pdgdrive.exe: pdgdrive.c
	$(CC) -O2 -mwindows -Wall pdgdrive.c -o pdgdrive.exe

windowdump.exe: windowdump.c
	$(CC) -O2 -mwindows -Wall windowdump.c -o windowdump.exe

clean:
	rm -f pdgdrive.exe windowdump.exe

.PHONY: all clean
