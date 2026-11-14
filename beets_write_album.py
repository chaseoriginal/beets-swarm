#!/usr/bin/env python3
"""Match a library item to the music file it belongs to, and write the
library's analysis tags to that file.

WHY A CUSTOM SCRIPT
-------------------
The bulk analyzer originally scoped its write with a beets id RANGE:

    beet write -f "id:<min>..<max>"

That is wrong in two ways:

1. The id lookup used a SQL LIKE '%<dir>%' pattern, which also matches
   album directories that merely SHARE A PREFIX with the one being
   processed. Measured: 48 of 546 albums had a LIKE scope larger than
   their own item set (e.g. 'General Music/Alicia Keys' matched 166
   items when it owns only 14). The resulting id range therefore covered
   OTHER albums' items.

2. `beet write -f` writes the DB's values to the files. For an item whose
   DB row has empty replaygain/acoustid values, that REMOVES the tags
   already in the file.

Together those mean the write pass for one album silently STRIPS the
analysis tags from the albums whose ids fell inside its range. That is
how the Lecrae "Gravity" album lost its tags after the bulk job had
correctly written them.

WHY THE MATCHING IS NOT BY PATH
-------------------------------
beets stores an item's path as the DESTINATION path computed from the
`paths:` template ($albumartist/$album%aunique{}/$track - $title), not
necessarily the file that is actually on disk. Example from this library:

    on disk : /music/General Music/10,000 Maniacs/The Wishing Chair (1985)/
              10,000 Maniacs - The Wishing Chair - 01 - Can't Ignore the Train.mp3
    in DB   : General Music/10,000 Maniacs/(1985)The Wishing Chair/
              - 01 10,000 Maniacs - Can't Ignore the Train.mp3

The directory name differs (%aunique{} moves the year to the front) and
the file name differs (the template rewrites it). What survives both
naming styles is the TRACK TITLE - the text after the last " - ".

So items are matched to files by title, restricted to the album, and the
tag write targets the on-disk file.

Usage (inside the beets container):
    python3 beets_write_album.py --ids  "<album dir>"   # print id regex
    python3 beets_write_album.py --write "<album dir>"   # write the tags
    python3 beets_write_album.py --map  "<album dir>"   # show the mapping
"""
import os
import re
import sqlite3
import sys

LIBRARY = "/config/musiclibrary.blb"
CONFIG = "/config/config.yaml"
MUSIC_ROOT = "/music"
AUDIO_EXT = (".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wma", ".aac")

# A leading track number in a file name: "01 - Title" or "- 01 Title".
_TRACK_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
# A disc subdirectory: "CD 02", "Disc 2", "CD1".
_DISC_RE = re.compile(r"^(cd|disc|disk|vinyl)\s*-?\s*\d+$", re.I)


def norm(text):
    """Normalise a name for comparison: lowercase, alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def title_of(path):
    """The track title from a file path: the text after the last ' - '."""
    base = os.path.splitext(os.path.basename(path))[0]
    parts = base.split(" - ")
    return norm(parts[-1] if len(parts) > 1 else base)


def track_of(path):
    """Best-effort track number, from a leading numeric token only."""
    base = os.path.splitext(os.path.basename(path))[0]
    for part in base.split(" - ")[:-1]:
        m = re.fullmatch(r"-?\s*(\d{1,3})", part.strip())
        if m:
            return m.group(1)
        # "- 01 10,000 Maniacs" style: a number right after the leading dash.
        m = re.match(r"^-\s*(\d{1,3})\s", part)
        if m:
            return m.group(1)
    return ""


def db_rows(lib_path):
    """Every library row: (id, path, album, track, title, artist)."""
    con = sqlite3.connect(lib_path)
    try:
        out = []
        for row in con.execute(
                "select id, path, album, track, title, artist from items"):
            item_id, path, album, track, title, artist = row
            vals = []
            for val in (path, album, track, title, artist):
                if isinstance(val, bytes):
                    val = val.decode("utf-8", "replace")
                vals.append(val or "")
            out.append((item_id,) + tuple(vals))
        return out
    finally:
        con.close()


def album_name_candidates(album_dir):
    """Album names that could identify this directory's album.

    For a plain album dir that is its own name (with and without a
    trailing year). For a disc subdirectory ("Better Dayz/CD 02") it is
    the parent's name as well.
    """
    names = set()
    parts = [p for p in album_dir.rstrip("/").split("/") if p]
    for depth in (1, 2):
        if len(parts) < depth:
            continue
        name = parts[-depth]
        if _DISC_RE.match(name.strip()):
            continue
        names.add(norm(name))
        names.add(norm(re.sub(r"\s*[\(\[]\d{4}[\)\]]\s*$", "", name)))
    return {n for n in names if n}


def disc_number(album_dir):
    """The disc number from a disc subdirectory name, or None."""
    parts = [p for p in album_dir.rstrip("/").split("/") if p]
    if not parts:
        return None
    name = parts[-1].strip()
    m = _DISC_RE.match(name)
    if not m:
        return None
    digits = re.search(r"(\d+)", name)
    return int(digits.group(1)) if digits else None


def disk_audio_files(album_dir):
    """The audio files directly in the album directory."""
    try:
        names = sorted(os.listdir(album_dir))
    except OSError:
        return []
    return [os.path.join(album_dir, n) for n in names
            if n.lower().endswith(AUDIO_EXT)]


def match_items(album_dir, rows=None):
    """Return [(item_id, db_path, disk_path)] for this album directory."""
    if rows is None:
        rows = db_rows(LIBRARY)

    rel = album_dir
    for pre in (MUSIC_ROOT + "/", "/config/Music/"):
        if rel.startswith(pre):
            rel = rel[len(pre):]
            break
    rel = rel.rstrip("/")

    # 1. Direct prefix match on the stored path.
    direct = [(r[0], r[1], None) for r in rows if r[1].startswith(rel + "/")]
    if direct:
        return direct

    # 2. Match by track title against the files on disk.
    disk = disk_audio_files(album_dir)
    if not disk:
        return []

    by_title = {}
    for p in disk:
        by_title.setdefault(title_of(p), []).append(p)

    album_names = album_name_candidates(album_dir)

    strict, loose = [], []
    for r in rows:
        t = title_of(r[1])
        if t not in by_title:
            continue
        album_n = norm(r[2])
        if album_n and album_n in album_names:
            strict.append(r)
        else:
            loose.append(r)

    candidates = strict or loose

    out = []
    for r in candidates:
        # Prefer the disk file whose basename matches exactly.
        target = None
        for p in by_title.get(title_of(r[1]), []):
            if os.path.basename(p) == os.path.basename(r[1]):
                target = p
                break
        if target is None:
            # Fall back on the track number.
            want = track_of(r[1])
            for p in by_title.get(title_of(r[1]), []):
                if want and track_of(p) == want:
                    target = p
                    break
        if target is None:
            target = by_title[title_of(r[1])][0]
        out.append((r[0], r[1], target))
    return out


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)

    mode, album_dir = args[0], args[1]

    if mode == "--ids":
        matched = match_items(album_dir)
        if not matched:
            return 1
        print("^(%s)$" % "|".join(str(m[0]) for m in sorted(matched)))
        return 0

    if mode == "--map":
        for item_id, db_path, disk_path in match_items(album_dir):
            print("  id=%-6s db=%-58s disk=%s" % (item_id, db_path[-58:], disk_path))
        return 0

    if mode == "--write":
        from beets import config
        config.set_file(CONFIG)
        from beets.library import Library

        lib = Library(LIBRARY)
        matched = match_items(album_dir)
        if not matched:
            print("no items matched")
            return 1

        written = 0
        skipped = 0
        for item_id, db_path, disk_path in matched:
            try:
                item = lib.get_item(item_id)
            except Exception:
                skipped += 1
                continue
            if item is None:
                skipped += 1
                continue
            # Write to the file that actually exists on disk.
            target = None
            for cand in (disk_path, db_path,
                         os.path.join(MUSIC_ROOT, db_path)):
                if cand and os.path.exists(cand):
                    target = cand
                    break
            if target is None:
                skipped += 1
                continue
            item.path = target
            try:
                item.try_write()
                written += 1
            except Exception as exc:
                print(f"write failed for {target}: {exc}")
                skipped += 1

        print(f"wrote {written} items, skipped {skipped}")
        return 0

    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
