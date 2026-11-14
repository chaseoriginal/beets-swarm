#!/usr/bin/env python3
"""Verify the analysis tags on disk for processed albums.

Run INSIDE the beets container. Reads the tags out of the FILES - the only
layer that proves the analysis reached the music.
"""
import glob
import os
import subprocess
import sys

MUSIC = "/music"


def tags_in_file(path):
    if path.lower().endswith(".flac"):
        out = subprocess.run(["metaflac", "--export-tags-to=-", path],
                             capture_output=True, text=True).stdout
    else:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format_tags",
             "-of", "default=nw=1", path],
            capture_output=True, text=True).stdout
    found = []
    for line in out.splitlines():
        up = line.upper()
        if "REPLAYGAIN" in up or "ACOUSTID" in up:
            key = line.split("=")[0].replace("TAG:", "").strip()
            found.append(key)
    return found


def main():
    ledger = sys.argv[1] if len(sys.argv) > 1 else "/tmp/done.list"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    try:
        with open(ledger) as fh:
            dirs = [l.strip() for l in fh if l.strip()]
    except OSError:
        print(f"no ledger at {ledger}")
        return 1

    dirs = dirs[-limit:]
    total = with_rg = with_fp = 0

    for host_dir in dirs:
        rel = host_dir
        for pre in ("/media/Multimedia/Music/",):
            if rel.startswith(pre):
                rel = rel[len(pre):]
                break
        cdir = os.path.join(MUSIC, rel)
        files = sorted(glob.glob(os.path.join(cdir, "*.flac")) +
                       glob.glob(os.path.join(cdir, "*.mp3")) +
                       glob.glob(os.path.join(cdir, "*.m4a")))
        if not files:
            print(f"   (no files) {os.path.basename(host_dir)}")
            continue
        for f in files[:3]:
            tags = tags_in_file(f)
            total += 1
            if any("REPLAYGAIN" in t for t in tags):
                with_rg += 1
            if any("ACOUSTID" in t for t in tags):
                with_fp += 1
            status = "OK " if len(tags) >= 4 else "LOW"
            print(f"   {status} tags={len(tags):<2} {os.path.basename(f)[:44]}")
            if tags:
                print(f"          {', '.join(sorted(set(tags)))}")

    print(f"\n   files with ReplayGain: {with_rg}/{total}   with fingerprint: {with_fp}/{total}")
    return 0 if total and with_rg == total else 1


if __name__ == "__main__":
    sys.exit(main())
