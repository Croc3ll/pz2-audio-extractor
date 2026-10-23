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


FORMATS = ["wem", "wav", "mp3", "ogg", "flac"]


def find_tool(path_or_name):
    """PATH, then an explicit path, then next to this exe/script (so users can just drop tools beside it)."""
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    beside = shutil.which(Path(path_or_name).name, path=str(here))
    return shutil.which(path_or_name) or (path_or_name if Path(path_or_name).is_file() else None) or beside


def convert(out_dir, fmt, vgmstream, ffmpeg):
    """Turn every extracted .wem into fmt; the .wem (and temp .wav) are removed on success."""
    wems = list(out_dir.rglob("*.wem"))
    ok = 0
    for i, wem in enumerate(wems, 1):
        wav = wem.with_suffix(".wav")
        if subprocess.run([vgmstream, "-o", str(wav), str(wem)], capture_output=True).returncode == 0:
            if fmt == "wav":
                ok += 1
                wem.unlink()
            else:
                dest = wem.with_suffix("." + fmt)
                r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), str(dest)],
                                   capture_output=True)
                wav.unlink()
                if r.returncode == 0:
                    ok += 1
                    wem.unlink()
        print(f"\r  converting {i}/{len(wems)}", end="", flush=True)
    print(f"\nConverted {ok}/{len(wems)} to .{fmt}" + (" (failed ones left as .wem)" if ok < len(wems) else ""))


def main():
    p = argparse.ArgumentParser(description="Extract Wwise audio from Planet Zoo 2 game files.")
    p.add_argument("game_dir", type=Path, help="Planet Zoo 2 install folder")
    p.add_argument("out_dir", type=Path, help="where to write extracted audio")
    p.add_argument("--all-files", action="store_true", help="scan every file, not just audio/archive extensions")
    p.add_argument("--format", choices=FORMATS, default="wem",
                   help="output format: wem (raw, default), wav (needs vgmstream-cli), mp3/ogg/flac (also need ffmpeg)")
    p.add_argument("--wav", action="store_const", const="wav", dest="format", help="same as --format wav")
    p.add_argument("--vgmstream", default="vgmstream-cli", help="path to vgmstream-cli (https://vgmstream.org)")
    p.add_argument("--ffmpeg", default="ffmpeg", help="path to ffmpeg (https://ffmpeg.org)")
    args = p.parse_args()

    if not args.game_dir.is_dir():
        sys.exit(f"Not a folder: {args.game_dir}")
    # Check the converters before a long scan, not after.
    vgmstream = ffmpeg = None
    if args.format != "wem":
        vgmstream = find_tool(args.vgmstream)
        if not vgmstream:
            sys.exit("vgmstream-cli not found; download it from https://vgmstream.org and put it next to this program (or pass --vgmstream)")
    if args.format not in ("wem", "wav"):
        ffmpeg = find_tool(args.ffmpeg)
        if not ffmpeg:
            sys.exit("ffmpeg not found; download it from https://ffmpeg.org and put it next to this program (or pass --ffmpeg)")

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

    if total and args.format != "wem":
        convert(args.out_dir, args.format, vgmstream, ffmpeg)
    elif total == 0 and not args.all_files:
        print("Nothing found. Try --all-files (audio may sit in other archive types).")


def ask_format():
    print("\nOutput format:")
    print("  1) wem   raw game files (no extra tools)")
    print("  2) wav   needs vgmstream-cli")
    print("  3) mp3   needs vgmstream-cli + ffmpeg")
    print("  4) ogg   needs vgmstream-cli + ffmpeg")
    print("  5) flac  needs vgmstream-cli + ffmpeg")
    while True:
        choice = input("Choose 1-5 [2]: ").strip().lower() or "2"
        if choice in FORMATS:
            return choice
        if choice.isdigit() and 1 <= int(choice) <= len(FORMATS):
            return FORMATS[int(choice) - 1]
        print("  Please enter a number from 1 to 5.")


def interactive():
    """Double-clicked with no arguments: ask for the folders and format instead."""
    print("Planet Zoo 2 Audio Extractor\n")
    game = input("Planet Zoo 2 install folder: ").strip().strip('"')
    out = input("Output folder [pz2_audio]: ").strip().strip('"') or "pz2_audio"
    sys.argv[1:] = [game, out, "--format", ask_format()]


if __name__ == "__main__":
    pause = len(sys.argv) == 1
    if pause:
        interactive()
    try:
        main()
    finally:
        if pause:
            input("\nDone. Press Enter to close.")
