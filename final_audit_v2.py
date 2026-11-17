#!/usr/bin/env python3
"""THE FINAL AUDIT - the closing numbers, read straight off the files.

Everything here is measured by READING THE FILES, never by counting
rows in a database or trusting a ledger. That is the lesson of this
whole job.

It reports, for the whole share and for the music library alone:
  - total files, by format
  - metadata completeness (title + artist + album)
  - analysis coverage (the six analysis fields)
  - the files that are still unreadable or undecodable

Usage: final_audit_v2.py [out.json]
"""
import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

AUDIO = ('.flac', '.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.wma', '.aac')
LIB_PREFIX = ('/music/General Music', '/music/Christian Music')


def probe(p):
    """One file -> a dict of everything measured from it."""
    out = {'p': p, 'ext': os.path.splitext(p)[1].lower(),
           'meta': False, 'an': 0, 'unreadable': False, 'damaged': False}
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format_tags',
             '-of', 'default=nw=1', p], capture_output=True, text=True,
            timeout=120)
        o = r.stdout.splitlines()
    except Exception:
        out['unreadable'] = True
        return out
    tags = {}
    for l in o:
        if '=' in l:
            k, v = l.split('=', 1)
            tags[k.split(':')[-1].strip().lower()] = v.strip()
    out['an'] = len([k for k in tags
                     if 'replaygain' in k or 'acoustid' in k])
    have = all(tags.get(k) for k in ('title', 'artist', 'album'))
    out['meta'] = bool(have)
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
        if ('Invalid data' in err or 'Error while decoding' in err
                or 'Invalid packet' in err):
            out['damaged'] = True
    except Exception:
        out['damaged'] = True
    return out


def main():
    outp = sys.argv[1] if len(sys.argv) > 1 else '/tmp/final_audit.json'
    files = []
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(root, f))
    files.sort()
    print('=== %d files ===' % len(files), flush=True)

    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=10) as ex:
        for res in ex.map(probe, files, chunksize=8):
            results.append(res)
            done += 1
            if done % 2000 == 0:
                print('   %d/%d' % (done, len(files)), flush=True)

    def report(name, subset):
        if not subset:
            print('\n=== %s: empty ===' % name)
            return {}
        n = len(subset)
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
            for d, c in dirs.most_common(12):
                print('      %3d  %s' % (c, d[-70:]))
            if len(lst) > 24:
                print('      ... and %d more' % (len(lst) - 24))
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
