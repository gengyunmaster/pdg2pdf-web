CC ?= i686-w64-mingw32-gcc

all: pdgdrive.exe

pdgdrive.exe: pdgdrive.c
	$(CC) -O2 -mwindows -Wall pdgdrive.c -o pdgdrive.exe

clean:
	rm -f pdgdrive.exe

.PHONY: all clean
