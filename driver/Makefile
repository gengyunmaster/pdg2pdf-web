# Plain assignment on purpose: make's built-in default (CC=cc) would defeat
# '?='. Command-line overrides still work: make CC=...
CC = i686-w64-mingw32-gcc

all: pdgdrive.exe windowdump.exe clickdump.exe

pdgdrive.exe: pdgdrive.c
	$(CC) -O2 -mwindows -Wall pdgdrive.c -o pdgdrive.exe

windowdump.exe: windowdump.c
	$(CC) -O2 -mwindows -Wall windowdump.c -o windowdump.exe

clickdump.exe: clickdump.c
	$(CC) -O2 -mwindows -Wall clickdump.c -o clickdump.exe

clean:
	rm -f pdgdrive.exe windowdump.exe clickdump.exe

.PHONY: all clean
