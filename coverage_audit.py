#!/usr/bin/env python3
"""Audit the music library for analysis-tag coverage.

Reads every audio file directly and reports, per format, how many files
carry the complete set of analysis tags. This is the ground truth: the
beets database is a claim, the file is the fact.

Usage:
    python3 coverage_audit.py [album-list-file]

With no argument, audits the entire library. With a file containing one
album directory per line (host paths), audits only those albums.

Must run INSIDE the beets container, where the share is /music.
"""
import os
import sys
import json
import subprocess
from collections import defaultdict

MUSIC = "/music"
AUDIO_EXT = {".flac", ".mp3", ".m4a", ".ogg", ".mp4", ".aac", ".opus", ".wma"}

# The six analysis fields the pipeline is responsible for.
REPLAYGAIN = [
    "replaygain_album_gain",
    "replaygain_album_peak",
    "replaygain_track_gain",
    "replaygain_track_peak",
]
ACOUSTID = ["acoustid_id", "acoustid_fingerprint"]


def audio_files(directory):
    out = []
    try:
        for entry in os.scandir(directory):
            if entry.is_file() and os.path.splitext(entry.name)[1].lower() in AUDIO_EXT:
                out.append(entry.path)
    except (PermissionError, FileNotFoundError):
        pass
    return out


def tags_of(path):
    """Return the set of analysis tag names present in the file."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format_tags",
             "-of", "default=nw=1", path],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    names = set()
    for line in proc.stdout.splitlines():
        if ":" not in line:
            continue
        key = line.split(":", 1)[0].strip().lower()
        if key.startswith("tag:"):
            key = key[4:]
        names.add(key)
    return names


def main():
    albums = []
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                # Host paths (/media/Multimedia/Music/...) -> container paths.
                if line.startswith("/media/Multimedia/Music"):
                    line = "/music" + line[len("/media/Multimedia/Music"):]
                albums.append(line)
    else:
        for root, dirs, _ in os.walk(MUSIC):
            if audio_files(root):
                albums.append(root)

    stats = defaultdict(lambda: {"files": 0, "full": 0, "no_rg": 0,
                                 "no_fp": 0, "unreadable": 0})
    per_album = []
    for album in albums:
        files = audio_files(album)
        a = {"album": album, "files": len(files), "full": 0, "partial": 0}
        for path in files:
            ext = os.path.splitext(path)[1].lower()
            s = stats[ext]
            s["files"] += 1
            names = tags_of(path)
            if names is None:
                s["unreadable"] += 1
                a["partial"] += 1
                continue
            has_rg = all(any(k.endswith(r) for k in names) for r in REPLAYGAIN)
            has_fp = any(any(k.endswith(c) for k in names) for c in ACOUSTID)
            if has_rg and has_fp:
                s["full"] += 1
                a["full"] += 1
            else:
                a["partial"] += 1
                if not has_rg:
                    s["no_rg"] += 1
                if not has_fp:
                    s["no_fp"] += 1
        per_album.append(a)

    print("=== ANALYSIS TAG COVERAGE (direct file reads) ===")
    tf = tfull = 0
    for ext in sorted(stats):
        s = stats[ext]
        tf += s["files"]
        tfull += s["full"]
        pct = (100.0 * s["full"] / s["files"]) if s["files"] else 0
        print(f"  {ext:6} {s['full']:6}/{s['files']:<6} {pct:5.1f}%   "
              f"missing_rg={s['no_rg']} missing_fp={s['no_fp']} "
              f"unreadable={s['unreadable']}")
    pct = (100.0 * tfull / tf) if tf else 0
    print(f"  {'TOTAL':6} {tfull:6}/{tf:<6} {pct:5.1f}%")
    print(f"  albums audited: {len(per_album)}  "
          f"fully tagged: {sum(1 for a in per_album if a['files'] and a['full'] == a['files'])}")
    incomplete = [a for a in per_album if a["partial"]]
    if incomplete:
        print(f"  albums with untagged files: {len(incomplete)}")
        for a in incomplete[:15]:
            print(f"     {a['full']}/{a['files']}  {a['album'][-70:]}")
    with open("/tmp/coverage.json", "w") as fh:
        json.dump({"stats": {k: dict(v) for k, v in stats.items()},
                   "albums": per_album}, fh, indent=1)


if __name__ == "__main__":
    main()
