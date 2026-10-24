# Planet Zoo 2 Audio Extractor

A small, dependency-free Python tool that pulls the sound effects, animal calls and music out of **Planet Zoo 2**.

Frontier's Cobra engine uses Audiokinetic Wwise. In Planet Zoo 2 the sound banks are stored as `.aux` files in `Win64/ovldata/Content0/Audio` (about 45,000 sounds: animals, music, crowds, ambience and so on). Every Wwise sound is a RIFF/WAVE blob; this tool scans for them, saves each as `.wem`, removes duplicates, and can convert them to `.wav` with [vgmstream](https://vgmstream.org).

## Download

Grab `pz2-audio-extractor.exe` from [Releases](https://github.com/Croc3ll/pz2-audio-extractor/releases) and double-click it. A window opens: browse to your game folder and an output folder, pick a format (wem, wav, mp3, ogg or flac), and click **Extract**. No Python needed. Everything is built in ([vgmstream](https://vgmstream.org) and [ffmpeg](https://ffmpeg.org)), so every format works straight away. (Windows SmartScreen may warn because the exe is unsigned: click "More info" → "Run anyway".)

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
| `--all-files` | Scan every file, not just `.aux .pck .bnk .wem .ovl .ovs` |
| `--format FMT` | `wem` (raw, default), `wav` (needs vgmstream), `mp3` / `ogg` / `flac` (needs vgmstream + ffmpeg). Converted `.wem` files are removed |
| `--wav` | Same as `--format wav` |
| `--vgmstream PATH` | Location of `vgmstream-cli` (default: PATH, or next to the program) |
| `--ffmpeg PATH` | Location of `ffmpeg` (default: PATH, or next to the program) |

## Sound names

Sounds are sorted into a folder per category (`animals`, `music`, `crowd`, `staff`, ...) and named after the Wwise event that plays them, e.g. `animals/ds_Vox_Call_BactrianCamel_adult_01.wav`. The number at the end separates variations of the same sound.

About 13,000 sounds get a real name. Sounds whose event name isn't known get `Unknown_<event id>_NN` (variations stay together), and sounds that no event plays get `Unknown_NN`. If a game update changes a sound, it falls back to `<source>_<offset>`.

The names come from `names.json.gz`, built by `tools/build_names.py` using [cobra-tools](https://github.com/OpenNaja/cobra-tools) (see the script for how to rerun it after a game update).

## Notes

- Extracted audio is Frontier's copyrighted material: for personal use only, don't redistribute it.
- Not affiliated with Frontier Developments.

## License

MIT. The release exe bundles [vgmstream](https://github.com/vgmstream/vgmstream) (r2117), under its own permissive license, and [ffmpeg](https://ffmpeg.org) (n8.1 LGPL build by [BtbN](https://github.com/BtbN/FFmpeg-Builds)), under the LGPL v3. Both license files are attached to each release. Sound names were derived with the help of [cobra-tools](https://github.com/OpenNaja/cobra-tools).
