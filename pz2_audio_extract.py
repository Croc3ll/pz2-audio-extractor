#!/usr/bin/env python3
"""Planet Zoo 2 audio extractor.

Frontier's Cobra engine ships its sound through Audiokinetic Wwise: banks (.bnk),
packages (.pck) and streamed files (.wem), sometimes packed inside other archives.
Every Wwise sound is a RIFF/WAVE blob, so this tool scans the game files for those
blobs, writes each one out as .wem, and (optionally) converts them to .wav with
vgmstream-cli.

Usage:
    python pz2_audio_extract.py "C:/Program Files (x86)/Steam/steamapps/common/Planet Zoo 2" out
    python pz2_audio_extract.py <game_dir> out --wav --vgmstream path/to/vgmstream-cli.exe
"""
import argparse
import hashlib
import mmap
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

DEFAULT_EXTS = {".pck", ".bnk", ".wem", ".ovl", ".ovs"}
MIN_BLOB = 64


def find_riff_blobs(data):
    """Yield (offset, size) for every RIFF/WAVE blob with a fmt chunk."""
    pos = data.find(b"RIFF")
    end = len(data)
    while pos != -1:
        if pos + 12 <= end and data[pos + 8:pos + 12] == b"WAVE":
            size = struct.unpack_from("<I", data, pos + 4)[0] + 8
            if MIN_BLOB <= size and pos + size <= end and data.find(b"fmt ", pos + 12, pos + 64) != -1:
                yield pos, size
                pos = data.find(b"RIFF", pos + size)
                continue
        pos = data.find(b"RIFF", pos + 4)


def scan_file(path, out_dir, seen, root):
    count = 0
    try:
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            rel = path.relative_to(root).with_suffix("")
            for offset, size in find_riff_blobs(data):
                blob = data[offset:offset + size]
                digest = hashlib.sha1(blob).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                target = out_dir / rel.parent / f"{rel.name}_{offset:08x}.wem"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
                count += 1
    except (ValueError, OSError) as e:  # empty or locked files
        if os.path.getsize(path):
            print(f"  skip {path}: {e}", file=sys.stderr)
    return count


def convert(out_dir, vgmstream):
    wems = list(out_dir.rglob("*.wem"))
    ok = 0
    for i, wem in enumerate(wems, 1):
        wav = wem.with_suffix(".wav")
        r = subprocess.run([vgmstream, "-o", str(wav), str(wem)], capture_output=True)
        if r.returncode == 0:
            ok += 1
        print(f"\r  converting {i}/{len(wems)}", end="", flush=True)
    print(f"\nConverted {ok}/{len(wems)} to .wav")


def main():
    p = argparse.ArgumentParser(description="Extract Wwise audio from Planet Zoo 2 game files.")
    p.add_argument("game_dir", type=Path, help="Planet Zoo 2 install folder")
    p.add_argument("out_dir", type=Path, help="where to write extracted audio")
    p.add_argument("--all-files", action="store_true", help="scan every file, not just audio/archive extensions")
    p.add_argument("--wav", action="store_true", help="convert .wem to .wav with vgmstream-cli")
    p.add_argument("--vgmstream", default=shutil.which("vgmstream-cli") or "vgmstream-cli",
                   help="path to vgmstream-cli (https://vgmstream.org)")
    args = p.parse_args()

    if not args.game_dir.is_dir():
        sys.exit(f"Not a folder: {args.game_dir}")
    files = [f for f in args.game_dir.rglob("*")
             if f.is_file() and (args.all_files or f.suffix.lower() in DEFAULT_EXTS)]
    print(f"Scanning {len(files)} files...")

    seen, total = set(), 0
    for f in files:
        n = scan_file(f, args.out_dir, seen, args.game_dir)
        if n:
            print(f"  {n:5d}  {f.relative_to(args.game_dir)}")
        total += n
    print(f"Extracted {total} unique sounds to {args.out_dir}")

    if total and args.wav:
        if not shutil.which(args.vgmstream) and not Path(args.vgmstream).is_file():
            sys.exit("vgmstream-cli not found; download it from https://vgmstream.org and pass --vgmstream")
        convert(args.out_dir, args.vgmstream)
    elif total == 0 and not args.all_files:
        print("Nothing found. Try --all-files (audio may sit in other archive types).")


if __name__ == "__main__":
    main()
