"""Build names.json.gz: maps each Planet Zoo 2 sound (by content hash) to a readable name.

Wwise only stores numeric IDs, so names are recovered the way cobra-tools' BNK editor does it:
event names (found as strings in the game's motiongraph/cinematic/fdb files, plus the
Planet Zoo / Planet Coaster 2 name lists) are hashed with FNV-1, matched to the events in each
*_Events bank, and followed down the Wwise hierarchy to the sounds they play.

This only needs to run when the game updates. It needs a checkout of cobra-tools
(https://github.com/OpenNaja/cobra-tools) and its requirements:

    python tools/build_names.py <cobra-tools dir> "<Planet Zoo 2 dir>" names.json.gz
"""
import gzip
import hashlib
import json
import logging
import os
import struct
import sys
import tempfile
from collections import Counter
from pathlib import Path

cobra, game_dir, out_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(cobra))
os.chdir(cobra)

from utils.logs import logging_setup  # noqa: E402

logging_setup("build_names")
logging.disable(logging.WARNING)

from constants import ConstantsProvider  # noqa: E402
from generated.formats.bnk import BnkFile  # noqa: E402
from generated.formats.bnk.enums.HircType import HircType  # noqa: E402
from generated.formats.ovl import OvlFile  # noqa: E402
from modules.formats.shared import fmt_hash, fnv1_32  # noqa: E402

GAME = "Planet Coaster 2"  # cobra-tools reads PZ2 archives with its PC2 settings (same engine)
SUFFIXES = ("", "_Start", "_Stop", "_OC", "_OC_Stop", "_OC_Start")
content = game_dir / "Win64" / "ovldata"


def add_name(lut, event):
    for suffix in SUFFIXES[1:]:
        event = event.removesuffix(suffix).removesuffix(suffix.lower())
    for suffix in SUFFIXES:
        s = event + suffix
        lut[fnv1_32(s.lower().encode())] = s


def build_lut():
    constants = ConstantsProvider()
    lut = {}
    for game in ("Planet Zoo", "Planet Coaster 2"):
        lut.update(constants[game].get("audio", {}))
    print(f"{len(lut)} names from cobra-tools lists")
    if os.environ.get("SKIP_WALK"):  # quick test: only the cobra-tools lists
        return lut
    ovl = OvlFile()
    ovl.load_hash_table()
    paths = sorted(content.rglob("*.ovl"))
    for i, path in enumerate(paths, 1):
        try:
            ovl.load(str(path), commands={"only_types": (".motiongraph", ".cinematic", ".fdb"), "game": GAME})
            for loader in ovl.loaders.values():
                for event in loader.get_audio_strings():
                    if event:
                        add_name(lut, event)
        except Exception:
            pass
        if i % 100 == 0:
            print(f"  walked {i}/{len(paths)} archives, {len(lut)} names")
    return lut


def extract_bnk(ovl_path, tmp):
    ovl = OvlFile()
    ovl.load(str(ovl_path), {"game": GAME})
    return [fp for fp in ovl.extract(tmp) if fp.endswith(".bnk")]


def children_of(hirc):
    if hasattr(hirc.data, "children"):
        return hirc.data.children
    if hasattr(hirc.data, "music_node_params"):
        return hirc.data.music_node_params.children
    return None


def walk(hirc, sid_2_hirc, name, wem_events, seen):
    if hirc.data.id in seen:
        return
    seen.add(hirc.data.id)
    children = children_of(hirc)  # may be a numpy array, so no truth test
    for child_id in set(children if children is not None else ()):
        child = sid_2_hirc.get(child_id)
        if child:
            walk(child, sid_2_hirc, name, wem_events, seen)
    sources = []
    if hirc.id == HircType.SOUND:
        sources = [hirc.data.ak_bank_source_data]
    elif hirc.id == HircType.MUSIC_TRACK:
        sources = hirc.data.ak_bank_source_data
    for sbi in sources:
        wem_events.setdefault(fmt_hash(sbi.ak_media_information.source_i_d), []).append(name)


def guess_name(event_names):
    """Same rule as cobra-tools: the name parts shared by every event that plays the sound."""
    names = [n for n in event_names if not n.startswith("0x")]
    if not names:
        # unnamed event: its id still keeps the variations of one sound together
        return f"Unknown_{min(event_names)[2:]}" if event_names else "Unknown"
    common = set.intersection(*[set(n.lower().split("_")) for n in names])
    parts = [x for x in names[0].split("_") if x.lower() in common]
    if len(parts) <= 1:
        parts.append("Shared")
    return "_".join(parts)


def riff_hash(data):
    data = bytes(data)
    if data[:4] == b"RIFF":
        data = data[:struct.unpack_from("<I", data, 4)[0] + 8]
    return hashlib.sha1(data).hexdigest()[:16]


def main():
    cache = os.environ.get("LUT_CACHE")  # optional: reuse the slow archive walk between runs
    if cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            lut = {int(k): v for k, v in json.load(f).items()}
    else:
        lut = build_lut()
        if cache:
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(lut, f)
    print(f"{len(lut)} event names in total")
    audio = content / "Content0" / "Audio"
    folders = {p.name.lower(): p for p in audio.iterdir() if p.is_dir()}
    table, stats = {}, Counter()
    for key, media_dir in sorted(folders.items()):
        if not key.endswith("_media"):
            continue
        bank = key[:-len("_media")]
        events_dir = folders.get(bank + "_events")
        with tempfile.TemporaryDirectory() as tmp:
            try:
                media_bnks = extract_bnk(next(media_dir.glob("*.ovl")), tmp)
                event_bnks = extract_bnk(next(events_dir.glob("*.ovl")), tmp) if events_dir else []
            except Exception as e:
                print(f"  {bank}: could not read ({e})")
                continue
            wem_events = {}
            for fp in event_bnks:
                events = BnkFile()
                events.load(fp)
                if not events.aux_b.hirc:
                    continue
                sid_2_hirc = {h.data.id: h for h in events.aux_b.hirc.hirc_pointers}
                for h in events.aux_b.hirc.hirc_pointers:
                    if h.id == HircType.EVENT:
                        name = lut.get(h.data.id, f"0x{fmt_hash(h.data.id)}")
                        walk(h, sid_2_hirc, name, wem_events, set())
            counts = Counter()
            for fp in media_bnks:
                media = BnkFile()
                media.load(fp)
                for wem_id, ptr in media.ptr_map.items():
                    if not getattr(ptr, "data", None):
                        continue
                    raw = guess_name(wem_events.get(wem_id, ()))
                    stats["unknown" if raw.startswith("Unknown") else "named"] += 1
                    table[riff_hash(ptr.data)] = f"{raw}_{counts[raw]:02d}"
                    counts[raw] += 1
            print(f"  {bank}: {sum(counts.values())} sounds")
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        json.dump(table, f, separators=(",", ":"))
    print(f"Wrote {len(table)} entries to {out_path}: {stats['named']} named, {stats['unknown']} unknown")


main()
