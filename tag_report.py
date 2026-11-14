#!/usr/bin/env python3
"""Report the analysis-tag count for EVERY file in the given albums.

Run inside the beets container. The ledger lists host paths; the albums
live under /music.
"""
import glob
import os
import subprocess
import sys

MUSIC = "/music"


def count_tags(path):
    if path.lower().endswith(".flac"):
        out = subprocess.run(["metaflac", "--export-tags-to=-", path],
                             capture_output=True, text=True).stdout
    else:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format_tags",
             "-of", "default=nw=1", path], capture_output=True, text=True).stdout
    hits = [l for l in out.splitlines()
            if "replaygain" in l.lower() or "acoustid" in l.lower()]
    return len(hits)


def main():
    ledger = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 8

    with open(ledger) as fh:
        dirs = [l.strip() for l in fh if l.strip()]

    total = good = 0
    by_ext = {}
    for host_dir in dirs[-limit:]:
        rel = host_dir
        if rel.startswith("/media/Multimedia/Music/"):
            rel = rel[len("/media/Multimedia/Music/"):]
        cdir = os.path.join(MUSIC, rel)
        files = sorted(glob.glob(os.path.join(cdir, "*")))
        files = [f for f in files
                 if f.lower().endswith((".flac", ".mp3", ".m4a", ".ogg"))]
        if not files:
            print(f"   (no files) {os.path.basename(host_dir)}")
            continue
        counts = []
        for f in files:
            n = count_tags(f)
            counts.append(n)
            total += 1
            ext = os.path.splitext(f)[1].lower()
            by_ext.setdefault(ext, [0, 0])
            by_ext[ext][1] += 1
            if n >= 4:
                good += 1
                by_ext[ext][0] += 1
        album = os.path.basename(host_dir)
        print(f"   {album[:44]:46s} files={len(files):3d} "
              f"tagged={sum(1 for c in counts if c >= 4):3d} "
              f"counts={sorted(set(counts))}")

    print(f"\n   files with >=4 analysis tags: {good}/{total}")
    for ext, (g, t) in sorted(by_ext.items()):
        print(f"     {ext:6s} {g}/{t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
