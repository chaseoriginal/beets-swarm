#!/usr/bin/env python3
"""Parallel scan for the two things that need action:

  A. UNREADABLE FILES - mutagen cannot parse them. These need to be
     REPLACED with a working copy.
  B. UNTAGGED FILES - fewer than 4 analysis atoms. These need the
     analysis pass re-run over their directories.

Runs as a shard: the parent launches N of these and merges.

Writes <out>.json with the full path lists (not just counts), so the
replacement and re-run tools can act on them.

Usage: scan_parallel.py <root> <shard-index> <shard-count> <out.json>
"""
import collections
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')
BADFILE_RE = re.compile(r'_\d{9,}$')


def probe(path):
    try:
        import mutagen
        f = mutagen.File(path)
    except Exception as exc:
        return None, 'mutagen-%s' % type(exc).__name__
    if f is None:
        try:
            size = os.path.getsize(path)
        except Exception:
            size = -1
        return None, 'no-format-%d' % size
    if f.tags is None:
        return 0, None
    try:
        keys = [k.decode('latin1').lower() if isinstance(k, bytes)
                else k.lower() for k in f.tags.keys()]
    except Exception:
        keys = []
    return len([k for k in keys if 'replaygain' in k or 'acoustid' in k]), None


def key_of(path):
    """A stable identity for a track, ignoring the duplicate marker."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = BADFILE_RE.sub('', stem)
    return re.sub(r'[^a-z0-9]+', '', stem.lower())


def main():
    root = sys.argv[1]
    idx = int(sys.argv[2])
    nsh = int(sys.argv[3])
    out = sys.argv[4]

    files = []
    for d, _s, fs in os.walk(root):
        for f in fs:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(d, f))
    mine = [p for i, p in enumerate(sorted(files)) if i % nsh == idx]
    print('shard %d/%d: %d files' % (idx, nsh, len(mine)))
    sys.stdout.flush()

    broken = []
    untagged = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for p, (n, err) in zip(mine, ex.map(probe, mine)):
            if err:
                broken.append({'path': p, 'reason': err})
            elif n < 4:
                untagged.append(p)
    print('shard %d: broken=%d untagged=%d' % (idx, len(broken), len(untagged)))
    sys.stdout.flush()

    with open(out, 'w') as fh:
        json.dump({'broken': broken, 'untagged': untagged}, fh)


if __name__ == '__main__':
    main()
