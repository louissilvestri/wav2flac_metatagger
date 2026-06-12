"""Dump the raw FLAC header + metadata block structure of a file.

Windows' FLAC property handler is strict: it needs 'fLaC' at byte 0 (no
prepended ID3) and well-formed metadata blocks. mutagen is far more tolerant,
so a file can read fine in the app yet show blank in Explorer.
"""
import struct
import sys
from pathlib import Path

_BLOCK_TYPES = {0: "STREAMINFO", 1: "PADDING", 2: "APPLICATION", 3: "SEEKTABLE",
                4: "VORBIS_COMMENT", 5: "CUESHEET", 6: "PICTURE", 127: "INVALID"}


def dump(path):
    with open(path, "rb") as f:
        head = f.read(4)
        print(f"\n{Path(path).name}")
        print(f"  first 4 bytes: {head!r}  ({'OK fLaC' if head == b'fLaC' else 'NOT FLAC MARKER'})")
        if head == b"ID3":
            print("  *** ID3 tag prepended — Windows will reject this file ***")
            return
        if head != b"fLaC":
            print(f"  *** unexpected header: {head.hex()} ***")
            return
        # Walk metadata blocks
        while True:
            hdr = f.read(4)
            if len(hdr) < 4:
                break
            b0 = hdr[0]
            last = bool(b0 & 0x80)
            btype = b0 & 0x7F
            size = struct.unpack(">I", b"\x00" + hdr[1:4])[0]
            name = _BLOCK_TYPES.get(btype, f"UNKNOWN({btype})")
            print(f"  block {name:15s} size={size:>8d} last={last}")
            f.seek(size, 1)
            if last:
                break


for p in sys.argv[1:]:
    dump(p)
