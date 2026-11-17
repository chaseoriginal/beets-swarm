#!/usr/bin/env python3
"""Parallel scan for files with CORRUPT AUDIO.

The single-process version took 13 minutes for 1,000 files over CIFS.
This uses 8 worker processes, which is ~8x faster, and writes the
result as JSON so it can be reused.

The test is a full decode:
    ffmpeg -v error -i FILE -f null -
Any "Invalid data" / "Error while decoding" line means the file is
damaged - ffmpeg can still produce a partial result, but the audio
stream is broken.

This matters because ONE damaged file poisons the ALBUM-level
ReplayGain of its whole album: beets' subprocess helper raises on a
non-zero exit, so the album gain is never computed and every other
track in that album loses its album gain too.

Usage: scan_corrupt_par.py [workers] [out.json]
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor

AUDIO = ('.flac', '.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.wma', '.aac')
BAD = ('Invalid data found', 'Error while decoding', 'Invalid packet',
       'Packet corrupt', 'error while decoding', 'Invalid nal unit')


def check(p):
    try:
        r = subprocess.run(
            ['ffmpeg', '-v', 'error', '-i', p, '-f', 'null', '-'],
            capture_output=True, text=True, timeout=180)
        err = r.stderr or ''
        hits = [l for l in err.splitlines() if any(b in l for b in BAD)]
        if hits:
            return (p, 'CORRUPT', hits[0][:110], len(hits))
        if r.returncode != 0:
            lines = err.splitlines()
            return (p, 'NONZERO', lines[0][:110] if lines else '', 0)
        return None
    except subprocess.TimeoutExpired:
        return (p, 'TIMEOUT', '', 0)
    except Exception as exc:
        return (p, 'ERROR', str(exc)[:110], 0)


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    outp = sys.argv[2] if len(sys.argv) > 2 else '/tmp/corrupt.json'
    files = []
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(root, f))
    files.sort()
    print('=== %d files, %d workers ===' % (len(files), workers), flush=True)
    bad = []
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(check, files, chunksize=16):
            done += 1
            if res:
                bad.append(res)
            if done % 2000 == 0:
                print('   %d/%d  corrupt=%d' % (done, len(files), len(bad)),
                      flush=True)
    print('')
    print('=== RESULT ===')
    print('   scanned %d, damaged %d' % (done, len(bad)))
    byext = {}
    for p, st, _m, _n in bad:
        e = os.path.splitext(p)[1].lower()
        byext[e] = byext.get(e, 0) + 1
    print('   by format: %s' % byext)
    bydir = {}
    for p, _st, _m, _n in bad:
        d = os.path.dirname(p)
        bydir[d] = bydir.get(d, 0) + 1
    print('   albums affected: %d' % len(bydir))
    with open(outp, 'w') as fh:
        json.dump({'scanned': done, 'bad': bad}, fh)
    print('   wrote %s' % outp)
    print('')
    print('=== the first 30 ===')
    for p, st, m, n in bad[:30]:
        print('   %-8s %-52s %s' % (st, p[-52:], m[:44]))


if __name__ == '__main__':
    main()
