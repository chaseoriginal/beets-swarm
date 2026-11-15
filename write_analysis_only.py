#!/usr/bin/env python3
"""Write ONLY the analysis fields to the music files, leaving every other
tag byte-for-byte alone.

WHY THIS EXISTS
---------------
Lidarr watches its root folder (/music/Christian Music). Any write to a
file Lidarr manages triggers its watcher, Lidarr refreshes the album and
REWRITES the file from its own database. Lidarr's tag writer drops
REPLAYGAIN_* and ACOUSTID_* because it does not know them - so a normal
beets write of the analysis tags was silently undone within a minute.

FLAC survived that fight (TagLib preserves unknown Vorbis comments);
MP3 did not (the ID3 frame set is replaced). Measured on this library:
FLAC 94/94 tagged, MP3 51/108.

Writing only the analysis fields, with mutagen, in place, keeps the
metadata exactly as it is and adds the six analysis tags.

Per format:
  FLAC -> a Vorbis comment (plain key)
  MP3  -> an ID3 TXXX frame (description + text)
  M4A  -> a freeform atom

Usage:
    python3 write_analysis_only.py <library.blb> <album-dir> [...]
"""
import os
import re
import sqlite3
import sys

# The only fields this script writes. Everything else is left alone.
ANALYSIS_FIELDS = {
    "rg_track_gain": "REPLAYGAIN_TRACK_GAIN",
    "rg_track_peak": "REPLAYGAIN_TRACK_PEAK",
    "rg_album_gain": "REPLAYGAIN_ALBUM_GAIN",
    "rg_album_peak": "REPLAYGAIN_ALBUM_PEAK",
    "acoustid_id": "ACOUSTID_ID",
    "acoustid_fingerprint": "ACOUSTID_FINGERPRINT",
}

MUSIC = "/music"
AUDIO_EXT = (".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus")


def norm(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def title_key(path):
    """(track number, normalised title) parsed from a file path.

    The track number is taken only from a LEADING numeric token: with a
    name like "10,000 Maniacs - The Wishing Chair - 01 - Can't Ignore the
    Train", a loose digit match picks up "000" from the artist.
    """
    base = os.path.splitext(os.path.basename(path))[0]
    parts = base.split(" - ")
    title = parts[-1] if len(parts) > 1 else base
    track = ""
    for part in parts[:-1]:
        m = re.fullmatch(r"-?\s*(\d{1,3})", part.strip())
        if m:
            track = m.group(1)
            break
    return track, norm(title)


def load_rows(db_path):
    """(relpath, basename, key, values) for every item in the library."""
    con = sqlite3.connect(db_path)
    try:
        cols = [r[1] for r in con.execute("pragma table_info(items)")]
        wanted = [c for c in ANALYSIS_FIELDS if c in cols]
        if not wanted:
            return []
        q = "select path, %s from items" % ",".join(wanted)
        out = []
        for row in con.execute(q):
            path = row[0]
            if isinstance(path, bytes):
                path = path.decode("utf-8", "replace")
            path = path or ""
            vals = dict(zip(wanted, row[1:]))
            rel = path
            for pre in (MUSIC + "/", "./"):
                if rel.startswith(pre):
                    rel = rel[len(pre):]
                    break
            rel = rel.lstrip("/")
            out.append((rel, os.path.basename(rel), title_key(rel), vals))
        return out
    finally:
        con.close()


def list_audio(root):
    """Every audio file under root, including one level of disc folders."""
    found = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return found
    for name in names:
        path = os.path.join(root, name)
        if os.path.isfile(path) and name.lower().endswith(AUDIO_EXT):
            found.append(path)
        elif os.path.isdir(path):
            # A disc subfolder (CD 02, Disc 2) holds more of the album.
            try:
                sub = sorted(os.listdir(path))
            except OSError:
                continue
            for s2 in sub:
                p2 = os.path.join(path, s2)
                if os.path.isfile(p2) and s2.lower().endswith(AUDIO_EXT):
                    found.append(p2)
    return found


def format_value(key, val):
    if val in (None, ""):
        return None
    if isinstance(val, bytes):
        val = val.decode("utf-8", "replace")
    val = str(val).strip()
    if not val:
        return None
    try:
        if key.endswith("_peak"):
            return "%.6f" % float(val)
        if key.endswith("_gain"):
            return "%.2f dB" % float(val)
    except (TypeError, ValueError):
        pass
    return val


def apply_to_file(path, values):
    """Set only the analysis fields. Returns the number of fields written."""
    wanted = {tag: format_value(key, values.get(key))
              for key, tag in ANALYSIS_FIELDS.items()}
    wanted = {k: v for k, v in wanted.items() if v is not None}
    if not wanted:
        return 0

    low = path.lower()
    try:
        if low.endswith(".flac"):
            from mutagen.flac import FLAC
            f = FLAC(path)
            kind = "flac"
        elif low.endswith(".mp3"):
            from mutagen.mp3 import MP3
            f = MP3(path)
            kind = "mp3"
        elif low.endswith((".m4a", ".mp4")):
            from mutagen.mp4 import MP4
            f = MP4(path)
            kind = "mp4"
        else:
            return 0
    except Exception as exc:
        print(f"   open failed {os.path.basename(path)}: {exc}")
        return 0

    written = 0
    for tag, val in wanted.items():
        try:
            if kind == "mp3":
                from mutagen.id3 import TXXX
                existing = [fr for fr in f.tags.getall("TXXX")
                            if fr.desc == tag]
                if existing:
                    existing[0].text = [val]
                else:
                    f.tags.add(TXXX(encoding=3, desc=tag, text=val))
            elif kind == "mp4":
                # MP4 needs the freeform iTunes atom. A plain key is stored
                # but ffprobe cannot read it back, so the tag would be
                # invisible to every player.
                f["----:com.apple.iTunes:" + tag] = [val.encode("utf-8")]
            else:
                f[tag] = [val]
            written += 1
        except Exception as exc:
            print(f"   set {tag} on {os.path.basename(path)}: {exc}")

    if written:
        try:
            f.save()
        except Exception as exc:
            print(f"   save failed {os.path.basename(path)}: {exc}")
            written = 0
    return written


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    db_path = sys.argv[1]
    dirs = sys.argv[2:]

    rows = load_rows(db_path)
    by_rel = {}
    by_base = {}
    by_key = {}
    by_title = {}
    for rel, base, key, vals in rows:
        by_rel[rel] = vals
        by_base.setdefault(base, vals)
        by_key.setdefault(key, vals)
        # A title-only index, for the case where the track number in the
        # file name does not match the one in the DB. Some releases have
        # two files with the same track number (a duplicate "03"), and
        # beets resolves the collision by renumbering one of them.
        by_title.setdefault(key[1], vals)

    total_files = 0
    total_written = 0
    unmatched = []
    for d in dirs:
        for path in list_audio(d):
            total_files += 1
            rel = path[len(MUSIC) + 1:] if path.startswith(MUSIC + "/") \
                else os.path.basename(path)
            vals = by_rel.get(rel)
            if vals is None:
                vals = by_base.get(os.path.basename(path))
            if vals is None:
                vals = by_key.get(title_key(path))
            if vals is None:
                # Fall back to the title alone.
                vals = by_title.get(title_key(path)[1])
            if vals is None:
                unmatched.append(os.path.basename(path))
                continue
            total_written += apply_to_file(path, vals)

    print(f"   files={total_files} fields_written={total_written} "
          f"unmatched={len(unmatched)}")
    for u in unmatched[:5]:
        print(f"      unmatched: {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
