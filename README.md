# Planet Zoo 2 Audio Extractor

A small, dependency-free Python tool that pulls the sound effects, animal calls and music out of **Planet Zoo 2**.

Frontier's Cobra engine uses Audiokinetic Wwise, so the audio lives in `.pck` / `.bnk` / `.wem` files (sometimes inside other archives). Every Wwise sound is a RIFF/WAVE blob; this tool scans for them, saves each as `.wem`, removes duplicates, and can convert them to `.wav` with [vgmstream](https://vgmstream.org).

## Download

Grab `pz2-audio-extractor.exe` from [Releases](https://github.com/Croc3ll/pz2-audio-extractor/releases) and double-click it. A window opens: browse to your game folder and an output folder, pick a format (wem, wav, mp3, ogg or flac), and click **Extract**. No Python needed. For anything other than wem, put [`vgmstream-cli.exe`](https://vgmstream.org) (and for mp3/ogg/flac, [`ffmpeg.exe`](https://ffmpeg.org)) next to the exe or on your PATH. (Windows SmartScreen may warn because the exe is unsigned: click "More info" → "Run anyway".)

## Requirements (running from source)

- Python 3.8+
- Optional: `vgmstream-cli` for `.wav` conversion ([download](https://vgmstream.org))

## Usage

```bash
python pz2_audio_extract.py "C:/Program Files (x86)/Steam/steamapps/common/Planet Zoo 2" out
```

Convert to another format:

```bash
python pz2_audio_extract.py "<game folder>" out --format mp3 --vgmstream C:/tools/vgmstream/vgmstream-cli.exe
```

| Option | What it does |
| --- | --- |
| `--all-files` | Scan every file, not just `.pck .bnk .wem .ovl .ovs` |
| `--format FMT` | `wem` (raw, default), `wav` (needs vgmstream), `mp3` / `ogg` / `flac` (needs vgmstream + ffmpeg). Converted `.wem` files are removed |
| `--wav` | Same as `--format wav` |
| `--vgmstream PATH` | Location of `vgmstream-cli` (default: PATH, or next to the program) |
| `--ffmpeg PATH` | Location of `ffmpeg` (default: PATH, or next to the program) |

Output keeps the game's folder layout; each file is named `<source>_<hex offset>.wem`.

## Notes

- Wwise sounds have numeric IDs, not names, so files won't have friendly names.
- Extracted audio is Frontier's copyrighted material: for personal use only, don't redistribute it.
- Not affiliated with Frontier Developments.

## License

MIT
