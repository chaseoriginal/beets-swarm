#!/usr/bin/env python3
"""Verify every album in a done-ledger actually has the analysis tags on
disk, and split the ledger into VERIFIED and NEEDS-WORK.

The ledger can contain false positives: an album recorded as done by a
runner that did not actually write the tags. Those albums would be
skipped forever. This checks the FILES, not the database, and produces a
new ledger containing only the albums that are genuinely done.
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
    return [l for l in out.splitlines()
            if "REPLAYGAIN" in l.upper() or "ACOUSTID" in l.upper()]


def main():
    src = sys.argv[1]
    out_verified = sys.argv[2]
    out_needs = sys.argv[3]

    with open(src) as fh:
        dirs = [l.strip() for l in fh if l.strip()]

    verified, needs = [], []
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
            needs.append(host_dir)
            continue
        ok = 0
        for f in files:
            if any("REPLAYGAIN" in t.upper() for t in tags_in_file(f)):
                ok += 1
        if ok == len(files):
            verified.append(host_dir)
        else:
            needs.append(host_dir)
            print(f"   NEEDS WORK {ok}/{len(files)} tags  {host_dir}")

    with open(out_verified, "w") as fh:
        fh.write("".join(d + "\n" for d in verified))
    with open(out_needs, "w") as fh:
        fh.write("".join(d + "\n" for d in needs))

    print(f"\n   verified: {len(verified)}   needs work: {len(needs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
