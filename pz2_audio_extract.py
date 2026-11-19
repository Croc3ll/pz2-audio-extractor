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
import gzip
import hashlib
import json
import mmap
import os
import re
import shutil
import struct
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_EXTS = {".aux", ".pck", ".bnk", ".wem", ".ovl", ".ovs"}
MIN_BLOB = 64


def find_riff_blobs(data):
    """Yield (offset, size) for every RIFF/WAVE blob with a believable fmt chunk."""
    pos = data.find(b"RIFF")
    end = len(data)
    while pos != -1:
        if pos + 12 <= end and data[pos + 8:pos + 12] == b"WAVE":
            size = struct.unpack_from("<I", data, pos + 4)[0] + 8
            if MIN_BLOB <= size and pos + size <= end and plausible_fmt(data, pos):
                yield pos, size
                pos = data.find(b"RIFF", pos + size)
                continue
        pos = data.find(b"RIFF", pos + 4)


def plausible_fmt(data, pos):
    """Bytes that only look like a RIFF header have nonsense channel counts or sample rates (like 684 MHz)."""
    fmt = data.find(b"fmt ", pos + 12, pos + 64)
    if fmt == -1 or fmt + 16 > len(data):
        return False
    channels, rate = struct.unpack_from("<HI", data, fmt + 10)
    return 1 <= channels <= 8 and 8000 <= rate <= 192000


def load_names():
    """Content hash -> sound name, built from the game's Wwise events by tools/build_names.py."""
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        with gzip.open(here / "names.json.gz", "rt", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def category_of(rel):
    """The output folder for a game file, relative to the game folder.

    animals_media_animals_media_bnk_S.aux -> animals (the game's audio folders are <category>_Media).
    Content_Localised/Audio/English(GB)/... -> voice/English(GB) (voice-over, one folder per language).
    """
    parts = rel.parts
    if "Content_Localised" in parts and "Audio" in parts[:-2]:
        return Path("voice", parts[parts.index("Audio") + 1])
    cut = rel.stem.lower().find("_media")
    return Path(rel.stem[:cut]) if cut > 0 else None


def safe(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def scan_file(path, out_dir, seen, root, names, only=""):
    count = 0
    try:
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            rel = path.relative_to(root).with_suffix("")
            category = category_of(path.relative_to(root))
            folder = out_dir / category if category else out_dir / rel.parent
            for offset, size in find_riff_blobs(data):
                blob = data[offset:offset + size]
                digest = hashlib.sha1(blob).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                name = names.get(digest[:16])
                target = folder / f"{safe(name)}.wem" if name else folder / f"{rel.name}_{offset:08x}.wem"
                if name and name.startswith("Unknown"):  # keep the named sounds easy to browse
                    target = folder / "unknown" / target.name
                if only and only not in target.stem.lower():
                    continue
                if target.exists():
                    target = target.with_name(f"{target.stem}_{offset:08x}.wem")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
                count += 1
    except (ValueError, OSError) as e:  # empty or locked files
        if os.path.getsize(path):
            print(f"  skip {path}: {e}", file=sys.stderr)
    return count


FORMATS = ["wem", "wav", "ogg", "flac"]
# ffmpeg's default OGG quality audibly muddies the game's 16 kHz sounds.
QUALITY = {"ogg": ["-q:a", "8"]}


def find_tool(path_or_name):
    """PATH, then an explicit path, then next to this exe/script, then the copy bundled inside the exe."""
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    name = Path(path_or_name).name
    beside = shutil.which(name, path=str(here))
    inside = Path(getattr(sys, "_MEIPASS", here))
    bundled = shutil.which(name, path=os.pathsep.join(str(inside / d) for d in ("vgmstream", "ffmpeg")))
    return shutil.which(path_or_name) or (path_or_name if Path(path_or_name).is_file() else None) or beside or bundled


def convert(out_dir, fmt, vgmstream, ffmpeg):
    """Turn every extracted .wem into fmt. If that step fails (or there's no ffmpeg) the sound stays as .wav.
    A .wem vgmstream can't decode at all is deleted: those are cut-off preload copies inside the .ovl
    archives (the full sound is in the .aux) or stray bytes that only look like a sound."""
    # No console window per call, and below-normal priority so the PC stays responsive during a long export.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)

    def to_wav(wem, wav):
        return subprocess.run([vgmstream, "-o", str(wav), str(wem)], capture_output=True,
                              creationflags=flags).returncode == 0

    def piped(wem, dest):
        """vgmstream decodes straight into ffmpeg, so no temporary .wav is written (less disk and virus-scan work)."""
        decode = subprocess.Popen([vgmstream, "-p", str(wem)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  creationflags=flags)
        encode = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
                                 *QUALITY.get(fmt, []), str(dest)], stdin=decode.stdout, capture_output=True,
                                creationflags=flags)
        decode.stdout.close()
        return decode.wait() == 0 and encode.returncode == 0

    def one(wem):
        wav, dest = wem.with_suffix(".wav"), wem.with_suffix("." + fmt)
        if fmt != "wav" and ffmpeg:
            if piped(wem, dest):
                wem.unlink()
                return fmt
            dest.unlink(missing_ok=True)
        if not to_wav(wem, wav):
            wem.unlink()
            wav.unlink(missing_ok=True)
            return "broken"
        wem.unlink()
        return "wav"

    wems = list(out_dir.rglob("*.wem"))
    results = Counter()
    # Half the cores: converting is quick, and leaving the rest free keeps games and browsers smooth.
    with ThreadPoolExecutor(max_workers=max(1, (os.cpu_count() or 4) // 2)) as pool:
        for i, result in enumerate(pool.map(one, wems), 1):
            results[result] += 1
            if i % 25 == 0 or i == len(wems):
                print(f"\r  converting {i}/{len(wems)}", end="", flush=True)
    print(f"\nConverted {results[fmt]}/{len(wems)} to .{fmt}")
    if fmt != "wav" and results["wav"]:
        print(f"  {results['wav']} couldn't be made .{fmt}, so they were saved as .wav instead")
    if results["broken"]:
        print(f"  Skipped {results['broken']} broken pieces (cut-off copies, not real sounds)")


def main(argv=None):
    p = argparse.ArgumentParser(description="Extract Wwise audio from Planet Zoo 2 game files.")
    p.add_argument("game_dir", type=Path, help="Planet Zoo 2 install folder")
    p.add_argument("out_dir", type=Path, help="where to write extracted audio")
    p.add_argument("--all-files", action="store_true", help="scan every file, not just audio/archive extensions")
    p.add_argument("--only", default="", help="only save sounds whose name contains this text, e.g. lion")
    p.add_argument("--format", choices=FORMATS, default="wem",
                   help="output format: wem (raw, default), wav (needs vgmstream-cli), flac/ogg (also need ffmpeg, "
                        "or they fall back to wav)")
    p.add_argument("--wav", action="store_const", const="wav", dest="format", help="same as --format wav")
    p.add_argument("--vgmstream", default="vgmstream-cli", help="path to vgmstream-cli (https://vgmstream.org)")
    p.add_argument("--ffmpeg", default="ffmpeg", help="path to ffmpeg (https://ffmpeg.org)")
    args = p.parse_args(argv)

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
            print(f"ffmpeg not found, so sounds will be saved as .wav instead of .{args.format}")

    files = [f for f in args.game_dir.rglob("*")
             if f.is_file() and (args.all_files or f.suffix.lower() in DEFAULT_EXTS)]
    print(f"Scanning {len(files)} files...")

    names = load_names()
    if names:
        print(f"Loaded {len(names)} sound names")
    seen, total = set(), 0
    for f in files:
        n = scan_file(f, args.out_dir, seen, args.game_dir, names, args.only.strip().lower())
        if n:
            print(f"  {n:5d}  {f.relative_to(args.game_dir)}")
        total += n
    print(f"Extracted {total} unique sounds to {args.out_dir}")

    if total and args.format != "wem":
        convert(args.out_dir, args.format, vgmstream, ffmpeg)
    elif total == 0 and not args.all_files:
        print("Nothing found. Try --all-files (audio may sit in other archive types).")


FORMAT_LABELS = {
    "flac": "FLAC: full quality, smaller than WAV (recommended)",
    "wav": "WAV: full quality, opens in everything",
    "ogg": "OGG: small, the format Hytale and many games use",
    "wem": "WEM: raw game files (needs a special player)",
}


def gui():
    """Opened with no arguments (e.g. double-clicked): show a window instead."""
    import queue
    import threading
    import tkinter as tk
    from tkinter import filedialog, ttk

    root = tk.Tk()
    root.title("Planet Zoo 2 Audio Extractor")
    root.minsize(560, 460)
    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    game = tk.StringVar()
    out = tk.StringVar(value=str(Path.home() / "Desktop" / "pz2_audio"))
    fmt = tk.StringVar(value="flac")
    all_files = tk.BooleanVar()
    only = tk.StringVar()

    def folder_row(row, label, var):
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=var).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(frm, text="Browse...", command=lambda: var.set(
            filedialog.askdirectory(title=label, initialdir=var.get() or None) or var.get())
        ).grid(row=row, column=2)

    folder_row(0, "Planet Zoo 2 folder:", game)
    folder_row(1, "Output folder:", out)

    box = ttk.LabelFrame(frm, text="Output format", padding=8)
    box.grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)
    for key, label in FORMAT_LABELS.items():
        ttk.Radiobutton(box, text=label, value=key, variable=fmt).pack(anchor="w")
    ttk.Checkbutton(frm, text="Scan every file (slower; use if nothing is found)",
                    variable=all_files).grid(row=3, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, text="Only names with:").grid(row=4, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=only).grid(row=4, column=1, sticky="ew", padx=6)
    ttk.Label(frm, text="e.g. lion (blank = all)").grid(row=4, column=2, sticky="w")

    start = ttk.Button(frm, text="Extract")
    start.grid(row=5, column=0, columnspan=3, pady=8)
    log = tk.Text(frm, height=12, state="disabled", wrap="word")
    log.grid(row=6, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(6, weight=1)

    lines = queue.Queue()

    class QueueWriter:
        def write(self, text):
            lines.put(text)

        def flush(self):
            pass

    def pump():
        while not lines.empty():
            text = lines.get()
            log.configure(state="normal")
            if text.startswith("\r"):  # progress line: overwrite the current one
                log.delete("end-1c linestart", "end-1c")
                text = text[1:]
            log.insert("end", text)
            log.see("end")
            log.configure(state="disabled")
        root.after(100, pump)

    def work(argv):
        sys.stdout = sys.stderr = QueueWriter()
        try:
            main(argv)
            print("\nDone!")
        except SystemExit as e:
            if e.code not in (None, 0):
                print(f"\nError: {e.code}")
        except Exception as e:
            print(f"\nError: {e}")
        finally:
            root.after(0, lambda: start.configure(state="normal"))

    def run():
        if not game.get().strip():
            lines.put("Pick your Planet Zoo 2 install folder first.\n")
            return
        argv = [game.get().strip(), out.get().strip() or "pz2_audio", "--format", fmt.get()]
        if all_files.get():
            argv.append("--all-files")
        if only.get().strip():
            argv += ["--only", only.get().strip()]
        start.configure(state="disabled")
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")
        threading.Thread(target=work, args=(argv,), daemon=True).start()

    start.configure(command=run)
    pump()
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        gui()
    else:
        main()
