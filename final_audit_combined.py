#!/usr/bin/env python3
"""THE FINAL AUDIT - one pass over the files, every measurement.

Two separate scans (one for coverage, one for corrupt audio) each
decoded every file, and running both together drove the host load
average to 81. This does ONE pass and takes every measurement from it:

  - metadata completeness (title + artist + album), read with ffprobe
  - analysis coverage (the six analysis fields)
  - whether mutagen can read the file
  - whether ffmpeg can DECODE the file (one full decode per file)

The decode is the expensive part, and it is also the measurement that
found the real fault - a file with corrupt audio that still carries
tags, which no tag-reading tool would ever reveal.

Parallelism is deliberately modest (4 workers): the bottleneck is CIFS
I/O, not CPU, and more workers just thrash.

Usage: final_audit_combined.py [workers] [out.json]
"""
import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

AUDIO = ('.flac', '.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.wma', '.aac')
LIB_PREFIX = ('/music/General Music', '/music/Christian Music')
BAD = ('Invalid data found', 'Error while decoding', 'Invalid packet',
       'Packet corrupt', 'error while decoding', 'Invalid nal unit')


def probe(p):
    out = {'p': p, 'ext': os.path.splitext(p)[1].lower(),
           'meta': False, 'an': 0, 'unreadable': False, 'damaged': False,
           'nofile': False}
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format_tags',
             '-of', 'default=nw=1', p], capture_output=True, text=True,
            timeout=120)
        o = r.stdout.splitlines()
    except Exception:
        out['unreadable'] = True
        out['nofile'] = True
        return out
    tags = {}
    for l in o:
        if '=' in l:
            k, v = l.split('=', 1)
            tags[k.split(':')[-1].strip().lower()] = v.strip()
    out['an'] = len([k for k in tags
                     if 'replaygain' in k or 'acoustid' in k])
    out['meta'] = all(tags.get(k) for k in ('title', 'artist', 'album'))
    try:
        import mutagen
        m = mutagen.File(p, easy=True)
        if m is None or m.tags is None:
            out['unreadable'] = True
    except Exception:
        out['unreadable'] = True
    try:
        r2 = subprocess.run(
            ['ffmpeg', '-v', 'error', '-i', p, '-f', 'null', '-'],
            capture_output=True, text=True, timeout=300)
        err = r2.stderr or ''
        if any(b in err for b in BAD):
            out['damaged'] = True
    except Exception:
        out['damaged'] = True
    return out


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    outp = sys.argv[2] if len(sys.argv) > 2 else '/tmp/final_audit.json'
    files = []
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(root, f))
    files.sort()
    print('=== %d files, %d workers ===' % (len(files), workers), flush=True)

    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(probe, files, chunksize=4):
            results.append(res)
            done += 1
            if done % 1000 == 0:
                print('   %d/%d' % (done, len(files)), flush=True)

    def report(name, subset):
        n = len(subset)
        if not n:
            return {}
        byext = Counter(r['ext'] for r in subset)
        meta = sum(1 for r in subset if r['meta'])
        an = sum(1 for r in subset if r['an'] >= 4)
        unread = [r for r in subset if r['unreadable']]
        dmg = [r for r in subset if r['damaged']]
        print('')
        print('=== %s ===' % name)
        print('   files:              %d' % n)
        print('   by format:          %s' % dict(sorted(byext.items())))
        print('   metadata complete:  %d (%.1f%%)' % (meta, meta * 100.0 / n))
        print('   analysis tagged:    %d (%.1f%%)' % (an, an * 100.0 / n))
        print('   unreadable:         %d' % len(unread))
        print('   undecodable:        %d' % len(dmg))
        for label, lst in (('UNREADABLE', unread), ('UNDECODABLE', dmg)):
            if not lst:
                continue
            print('   --- %s ---' % label)
            dirs = Counter(os.path.dirname(r['p']) for r in lst)
            for d, c in dirs.most_common(10):
                print('      %3d  %s' % (c, d[-68:]))
            if len(lst) > 20:
                print('      ... and %d more' % (len(lst) - 20))
        return {'files': n, 'meta': meta, 'analysis': an,
                'unreadable': len(unread), 'damaged': len(dmg),
                'byext': dict(byext)}

    lib = [r for r in results if r['p'].startswith(LIB_PREFIX)]
    allr = report('WHOLE SHARE', results)
    libr = report('MUSIC LIBRARY', lib)

    with open(outp, 'w') as fh:
        json.dump({'all': allr, 'library': libr,
                   'unreadable': [r['p'] for r in results if r['unreadable']],
                   'damaged': [r['p'] for r in results if r['damaged']]},
                  fh)
    print('')
    print('wrote %s' % outp)


if __name__ == '__main__':
    main()
