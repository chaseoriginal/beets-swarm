#!/usr/bin/env python3
"""A FAST, SAMPLED count of the files with corrupt audio, plus the
full list for the albums that matter.

The full 49,560-file scan takes hours over CIFS. This takes a
statistically valid SAMPLE (every Nth file, so it is spread across the
whole library rather than clustered) with 12 workers, and reports the
rate. It also does a FULL scan of any directory named on the command
line, so the albums that failed the analysis pass get an exact answer.

Usage: scan_corrupt_sampled.py [sample_size] [dir ...]
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
            capture_output=True, text=True, timeout=240)
        err = r.stderr or ''
        hits = [l for l in err.splitlines() if any(b in l for b in BAD)]
        if hits:
            return (p, 'CORRUPT', hits[0][:100], len(hits))
        if r.returncode != 0:
            lines = err.splitlines()
            return (p, 'NONZERO', lines[0][:100] if lines else '', 0)
        return None
    except subprocess.TimeoutExpired:
        return (p, 'TIMEOUT', '', 0)
    except Exception as exc:
        return (p, 'ERROR', str(exc)[:100], 0)


def collect():
    files = []
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(root, f))
    files.sort()
    return files


def main():
    sample = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    dirs = sys.argv[2:]
    files = collect()
    print('=== %d files total ===' % len(files), flush=True)

    # the sample: every Nth file, so it is spread across the library
    step = max(1, len(files) // sample)
    sampled = files[::step][:sample]
    # plus a full scan of the named directories
    extra = []
    for d in dirs:
        for root, _s, fs in os.walk(d):
            for f in fs:
                if f.lower().endswith(AUDIO):
                    extra.append(os.path.join(root, f))
    todo = sorted(set(sampled) | set(extra))
    print('=== scanning %d (%d sampled + %d in the named dirs) ==='
          % (len(todo), len(sampled), len(extra)), flush=True)

    bad = []
    done = 0
    with ProcessPoolExecutor(max_workers=12) as ex:
        for res in ex.map(check, todo, chunksize=8):
            done += 1
            if res:
                bad.append(res)
            if done % 1000 == 0:
                print('   %d/%d corrupt=%d' % (done, len(todo), len(bad)),
                      flush=True)

    sampled_set = set(sampled)
    s_bad = [b for b in bad if b[0] in sampled_set]
    rate = len(s_bad) / max(1, len(sampled))
    print('')
    print('=== RESULT ===')
    print('   sample: %d files, %d corrupt = %.2f%%'
          % (len(sampled), len(s_bad), rate * 100))
    print('   extrapolated to %d files: %d'
          % (len(files), int(rate * len(files))))
    print('   full scan of the named dirs: %d corrupt' % len(bad) - len(s_bad)
          if False else '   total found: %d' % len(bad))
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
    print('')
    print('   the albums (count, name):')
    for d, n in sorted(bydir.items(), key=lambda x: -x[1])[:25]:
        print('      %3d  %s' % (n, d[-72:]))
    with open('/tmp/corrupt_sample.json', 'w') as fh:
        json.dump({'sample': len(sampled), 'sample_bad': len(s_bad),
                   'rate': rate, 'total_files': len(files),
                   'bad': bad}, fh)
    print('   wrote /tmp/corrupt_sample.json')


if __name__ == '__main__':
    main()
