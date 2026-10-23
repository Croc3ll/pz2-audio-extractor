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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEFAULT_EXTS = {".aux", ".pck", ".bnk", ".wem", ".ovl", ".ovs"}
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
    """PATH, then an explicit path, then next to this exe/script, then the copy bundled inside the exe."""
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    name = Path(path_or_name).name
    beside = shutil.which(name, path=str(here))
    bundled = shutil.which(name, path=str(Path(getattr(sys, "_MEIPASS", here)) / "vgmstream"))
    return shutil.which(path_or_name) or (path_or_name if Path(path_or_name).is_file() else None) or beside or bundled


def convert(out_dir, fmt, vgmstream, ffmpeg):
    """Turn every extracted .wem into fmt; the .wem (and temp .wav) are removed on success."""
    # No console window popping up per call when running as the windowed exe.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def one(wem):
        wav = wem.with_suffix(".wav")
        if subprocess.run([vgmstream, "-o", str(wav), str(wem)], capture_output=True, creationflags=flags).returncode:
            return False
        if fmt != "wav":
            r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), str(wem.with_suffix("." + fmt))],
                               capture_output=True, creationflags=flags)
            wav.unlink()
            if r.returncode:
                return False
        wem.unlink()
        return True

    wems = list(out_dir.rglob("*.wem"))
    ok = 0
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        for i, done in enumerate(pool.map(one, wems), 1):
            ok += done
            if i % 25 == 0 or i == len(wems):
                print(f"\r  converting {i}/{len(wems)}", end="", flush=True)
    print(f"\nConverted {ok}/{len(wems)} to .{fmt}" + (" (failed ones left as .wem)" if ok < len(wems) else ""))


def main(argv=None):
    p = argparse.ArgumentParser(description="Extract Wwise audio from Planet Zoo 2 game files.")
    p.add_argument("game_dir", type=Path, help="Planet Zoo 2 install folder")
    p.add_argument("out_dir", type=Path, help="where to write extracted audio")
    p.add_argument("--all-files", action="store_true", help="scan every file, not just audio/archive extensions")
    p.add_argument("--format", choices=FORMATS, default="wem",
                   help="output format: wem (raw, default), wav (needs vgmstream-cli), mp3/ogg/flac (also need ffmpeg)")
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


FORMAT_LABELS = {
    "wem": "WEM: raw game files (no extra tools)",
    "wav": "WAV: playable audio",
    "mp3": "MP3: needs ffmpeg",
    "ogg": "OGG: needs ffmpeg",
    "flac": "FLAC: needs ffmpeg",
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
    fmt = tk.StringVar(value="wav")
    all_files = tk.BooleanVar()

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

    start = ttk.Button(frm, text="Extract")
    start.grid(row=4, column=0, columnspan=3, pady=8)
    log = tk.Text(frm, height=12, state="disabled", wrap="word")
    log.grid(row=5, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(5, weight=1)

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
