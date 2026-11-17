#!/usr/bin/env python3
"""SCOPE CHECK: how many library files have corrupt audio?

This started as an analysis bug - the album-level ReplayGain pass
fails with "ffmpeg exited with status 234" on any album containing a
file that ffmpeg cannot fully decode. beets' `call()` raises on a
non-zero exit, so ONE bad file poisons the whole album's gain.

SevenDust "All I See Is War (2018)" is the example: its 12 .m4a files
each produce HUNDREDS of "Invalid data found when processing input"
decode errors, and they stop the album gain for the 12 perfectly
clean .mp3 files sitting beside them.

That is a file-integrity problem, not just a beets problem. This
sweeps the library and counts the files ffmpeg cannot decode cleanly.

The test is a full decode to null:
    ffmpeg -v error -i FILE -f null -
Any "Invalid data" / "Error while decoding" line means the file is
damaged.

Usage: scan_corrupt.py [--sample N]
"""
import os
import subprocess
import sys

AUDIO = ('.flac', '.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.wma', '.aac')
BAD = ('Invalid data found', 'Error while decoding', 'Invalid packet',
       'concealing', 'Packet corrupt', 'error while decoding')


def decode_errors(path):
    try:
        r = subprocess.run(
            ['ffmpeg', '-v', 'error', '-xerror', '-i', path, '-f', 'null', '-'],
            capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return 'TIMEOUT', ''
    except Exception as exc:
        return 'ERROR', str(exc)
    err = r.stderr or ''
    hits = [l for l in err.splitlines() if any(b in l for b in BAD)]
    if hits:
        return 'CORRUPT', '%s (%d)' % (hits[0][:90], len(hits))
    if r.returncode != 0:
        return 'NONZERO', err.splitlines()[0][:90] if err.splitlines() else ''
    return 'OK', ''


def main():
    sample = None
    if '--sample' in sys.argv:
        sample = int(sys.argv[sys.argv.index('--sample') + 1])
    files = []
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(root, f))
    files.sort()
    if sample:
        step = max(1, len(files) // sample)
        files = files[::step][:sample]
    print('=== scanning %d files ===' % len(files))
    counts = {'OK': 0, 'CORRUPT': 0, 'NONZERO': 0, 'TIMEOUT': 0, 'ERROR': 0}
    bad = []
    for i, p in enumerate(files):
        st, msg = decode_errors(p)
        counts[st] = counts.get(st, 0) + 1
        if st != 'OK':
            bad.append((p, st, msg))
        if (i + 1) % 500 == 0:
            print('   %d/%d  %s' % (i + 1, len(files), counts), flush=True)
    print('')
    print('=== RESULT ===')
    for k, v in sorted(counts.items()):
        print('   %-8s %d' % (k, v))
    print('')
    print('=== the damaged files ===')
    byext = {}
    for p, st, msg in bad:
        e = os.path.splitext(p)[1].lower()
        byext[e] = byext.get(e, 0) + 1
    print('   by format: %s' % byext)
    for p, st, msg in bad[:40]:
        print('   %-8s %-56s %s' % (st, p[-56:], msg[:50]))


if __name__ == '__main__':
    main()
