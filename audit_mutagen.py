#!/usr/bin/env python3
"""The analysis-coverage measurement, by MUTAGEN, on the same sample.

The ffprobe-based audit and the earlier mutagen-based measurement
disagreed (75.2% vs 78.6% of the library). The likely cause is
ffprobe's rendering of ID3 TXXX frames on MP3: it shows the frame
DESCRIPTION as the key, so a frame written with a description that is
not the field name does not match a search for "replaygain".

This measures the ACTUAL tag keys with mutagen, which is
authoritative, on the SAME every-8th-file sample, and reports both
methods side by side so the difference is visible rather than assumed.

Usage: audit_mutagen.py [sample_size] [out.json]
"""
import json
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

import mutagen

AUDIO = ('.flac', '.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.wma', '.aac')
LIB_PREFIX = ('/music/General Music', '/music/Christian Music')
FIELDS = ('ACOUSTID_ID', 'ACOUSTID_FINGERPRINT',
          'REPLAYGAIN_ALBUM_GAIN', 'REPLAYGAIN_ALBUM_PEAK',
          'REPLAYGAIN_TRACK_GAIN', 'REPLAYGAIN_TRACK_PEAK')


def read(p):
    """Count the analysis fields by their real names."""
    out = {'p': p, 'ext': os.path.splitext(p)[1].lower(),
           'have': 0, 'names': set(), 'meta': False}
    try:
        f = mutagen.File(p, easy=False)
    except Exception:
        return out
    if f is None or f.tags is None:
        return out
    keys = set()
    try:
        for k in f.tags.keys():
            keys.add(str(k).upper())
    except Exception:
        pass
    # FLAC keeps them as VORBIS keys; MP3 as TXXX; M4A in freeform
    # atoms. Look for the field name anywhere in the key, and also
    # read the freeform/description payload.
    found = set()
    for k in keys:
        for fld in FIELDS:
            if fld in k:
                found.add(fld)
    # MP3 TXXX: the key is the description, so scan the values too
    try:
        for k, v in f.tags.items():
            desc = str(k)
            if desc.upper() in FIELDS:
                found.add(desc.upper())
            if desc.upper() == 'TXXX':
                for item in v:
                    text = '\n'.join(str(x) for x in item)
                    for fld in FIELDS:
                        if fld in text.upper():
                            found.add(fld)
    except Exception:
        pass
    out['have'] = len(found)
    # metadata
    try:
        e = mutagen.File(p, easy=True)
        if e is not None and e.tags is not None:
            d = {k.lower(): v for k, v in e.tags.items()}
            out['meta'] = all(d.get(k) for k in ('title', 'artist', 'album'))
    except Exception:
        pass
    return out


def main():
    sample = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    outp = sys.argv[2] if len(sys.argv) > 2 else '/tmp/mutagen_audit.json'
    files = []
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(root, f))
    files.sort()
    step = max(1, len(files) // sample)
    sampled = files[::step][:sample]
    print('=== %d files, sampling %d (every %dth) ==='
          % (len(files), len(sampled), step), flush=True)

    res = []
    done = 0
    with ProcessPoolExecutor(max_workers=8) as ex:
        for r in ex.map(read, sampled, chunksize=16):
            res.append(r)
            done += 1
            if done % 2000 == 0:
                print('   %d/%d' % (done, len(sampled)), flush=True)

    def report(name, subset):
        n = len(subset)
        if not n:
            return {}
        byext = Counter(r['ext'] for r in subset)
        meta = sum(1 for r in subset if r['meta'])
        full = sum(1 for r in subset if r['have'] >= 4)
        six = sum(1 for r in subset if r['have'] >= 6)
        print('')
        print('   --- %s (n=%d) ---' % (name, n))
        print('      by format:        %s' % dict(sorted(byext.items())))
        print('      metadata complete:%d (%.1f%%)'
              % (meta, meta * 100.0 / n))
        print('      >=4 analysis flds:%d (%.1f%%)'
              % (full, full * 100.0 / n))
        print('      all 6 fields:     %d (%.1f%%)'
              % (six, six * 100.0 / n))
        for e in sorted(byext):
            sub = [r for r in subset if r['ext'] == e]
            f4 = sum(1 for r in sub if r['have'] >= 4)
            print('         %-6s %4d files, %5.1f%% tagged'
                  % (e, len(sub), f4 * 100.0 / len(sub)))
        return {'n': n, 'meta': meta, 'ge4': full, 'ge6': six,
                'byext': dict(byext)}

    lib = [r for r in res if r['p'].startswith(LIB_PREFIX)]
    allr = report('WHOLE SHARE (sampled)', res)
    libr = report('MUSIC LIBRARY (sampled)', lib)
    with open(outp, 'w') as fh:
        json.dump({'all': allr, 'library': libr, 'sample': len(sampled),
                   'total_files': len(files)}, fh)
    print('')
    print('wrote %s' % outp)


if __name__ == '__main__':
    main()
