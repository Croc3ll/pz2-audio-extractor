# Planet Zoo 2 Audio Extractor

A small, dependency-free Python tool that pulls the sound effects, animal calls and music out of **Planet Zoo 2**.

Frontier's Cobra engine uses Audiokinetic Wwise, so the audio lives in `.pck` / `.bnk` / `.wem` files (sometimes inside other archives). Every Wwise sound is a RIFF/WAVE blob; this tool scans for them, saves each as `.wem`, removes duplicates, and can convert them to `.wav` with [vgmstream](https://vgmstream.org).

## Requirements

- Python 3.8+
- Optional: `vgmstream-cli` for `.wav` conversion ([download](https://vgmstream.org))

## Usage

```bash
python pz2_audio_extract.py "C:/Program Files (x86)/Steam/steamapps/common/Planet Zoo 2" out
```

Convert to WAV as well:

```bash
python pz2_audio_extract.py "<game folder>" out --wav --vgmstream C:/tools/vgmstream/vgmstream-cli.exe
```

| Option | What it does |
| --- | --- |
| `--all-files` | Scan every file, not just `.pck .bnk .wem .ovl .ovs` |
| `--wav` | Convert extracted `.wem` to `.wav` |
| `--vgmstream PATH` | Location of `vgmstream-cli` (default: found on PATH) |

Output keeps the game's folder layout; each file is named `<source>_<hex offset>.wem`.

## Notes

- Wwise sounds have numeric IDs, not names, so files won't have friendly names.
- Extracted audio is Frontier's copyrighted material: for personal use only, don't redistribute it.
- Not affiliated with Frontier Developments.

## License

MIT
