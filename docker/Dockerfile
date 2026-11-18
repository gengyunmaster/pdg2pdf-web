# Phase A image: Debian + Wine32 + Xvfb + the web service.
#
# The Pdg2Pic binary is NOT shipped in this repository (BYOB). Place
# Pdg2Pic.exe (obtain it from the author's page, see README.md) into
# vendor/ before building, or mount it at runtime.

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    WINEDEBUG=-1

# Wine32 (the app is a 32-bit PE), Xvfb for headless GUI, 7z for archives,
# MinGW to cross-compile the Win32 driver at build time.
RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
        wine32 xvfb p7zip-full p7zip-rar \
        python3 python3-pip \
        gcc-mingw-w64-i686 make \
        ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Python dependencies
COPY requirements.txt ./
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

# Application + driver build + bundled archive-password word list
COPY app ./app
COPY driver ./driver
COPY wordlists ./wordlists
RUN make -C driver \
 && rm -rf driver/*.o

# Initialize a Wine prefix at build time so first boot is fast.
# BYOB: uncomment the next line after placing Pdg2Pic.exe in vendor/.
# COPY vendor/Pdg2Pic.exe /srv/vendor/Pdg2Pic.exe
RUN mkdir -p /srv/vendor \
 && WINEPREFIX=/srv/.wine xvfb-run -a wine wineboot --init \
 && wineserver -w || true

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PDG2PDF_CONVERTER=wine_pdg2pic \
    PDG2PIC_EXE=/srv/vendor/Pdg2Pic.exe \
    PDG2PDF_DATA_DIR=/srv/data \
    WINEPREFIX=/srv/.wine

EXPOSE 8000
CMD ["/entrypoint.sh"]
