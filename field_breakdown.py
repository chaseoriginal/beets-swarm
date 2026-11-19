#!/usr/bin/env python3
"""WHICH analysis fields are present, and on how many files.

The coverage audit says 75.6% of the share carries at least 4 of the
6 analysis fields, but only 4.5% carries all 6. That gap has to be
explained: either the AcoustID pair is not landing, or the album gain
and peak are not landing, or both.

This breaks it down by field, per format, and lists the albums with
the least coverage so a targeted re-run can be built from the list.

It also rebuilds a WORK LIST of the directories that still need work,
the same way the original untagged list was built - so a v7 pass has
a target list.

Usage: field_breakdown.py [out.json]
"""
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor

import mutagen

AUDIO = ('.flac', '.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.wma', '.aac')
LIB_PREFIX = ('/music/General Music', '/music/Christian Music')
FIELDS = ('ACOUSTID_ID', 'ACOUSTID_FINGERPRINT',
          'REPLAYGAIN_ALBUM_GAIN', 'REPLAYGAIN_ALBUM_PEAK',
          'REPLAYGAIN_TRACK_GAIN', 'REPLAYGAIN_TRACK_PEAK')


def fields_of(p):
    try:
        f = mutagen.File(p, easy=False)
    except Exception:
        return None
    if f is None or f.tags is None:
        return set()
    found = set()
    try:
        for k, v in f.tags.items():
            desc = str(k).upper()
            if desc in FIELDS:
                found.add(desc)
            if desc == 'TXXX':
                for item in v:
                    text = '\n'.join(str(x) for x in item).upper()
                    for fld in FIELDS:
                        if fld in text:
                            found.add(fld)
            else:
                for fld in FIELDS:
                    if fld in desc:
                        found.add(fld)
    except Exception:
        pass
    return found


def main():
    outp = sys.argv[1] if len(sys.argv) > 1 else '/tmp/field_breakdown.json'
    files = []
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(root, f))
    files.sort()
    step = max(1, len(files) // 6000)
    sampled = files[::step][:6000]
    print('=== %d files, sampling %d ===' % (len(files), len(sampled)),
          flush=True)

    res = []
    done = 0
    with ProcessPoolExecutor(max_workers=8) as ex:
        for r in ex.map(fields_of, sampled, chunksize=16):
            res.append((sampled[done], r))
            done += 1
            if done % 2000 == 0:
                print('   %d/%d' % (done, len(sampled)), flush=True)

    byext = defaultdict(Counter)
    present = Counter()
    total = Counter()
    albums = defaultdict(lambda: {'n': 0, 'ok': 0})
    for p, found in res:
        e = os.path.splitext(p)[1].lower()
        total[e] += 1
        if found is None:
            continue
        for fld in FIELDS:
            if fld in found:
                present[fld] += 1
                byext[e][fld] += 1
        d = os.path.dirname(p)
        albums[d]['n'] += 1
        if len(found) >= 4:
            albums[d]['ok'] += 1

    print('')
    print('=== per field, by format ===')
    print('   %-26s %s' % ('field', '  '.join('%8s' % e for e in sorted(total))))
    for fld in FIELDS:
        row = '   %-26s ' % fld
        for e in sorted(total):
            row += '%7.1f%% ' % (byext[e][fld] * 100.0 / total[e])
        print(row)
    print('')
    print('   %-26s %s' % ('', '  '.join('%8s' % e for e in sorted(total))))
    for e in sorted(total):
        print('   %-26s %8d' % ('files', total[e]))

    # the worst albums
    worst = sorted(albums.items(),
                   key=lambda kv: (kv[1]['ok'] - kv[1]['n']))[:25]
    print('')
    print('=== the albums with the least coverage ===')
    for d, s in worst:
        if s['n'] - s['ok'] <= 0:
            break
        print('   %3d/%3d tagged   %s' % (s['ok'], s['n'], d[-70:]))

    # a work list of the directories that still need work
    work = sorted(d for d, s in albums.items() if s['ok'] < s['n'])
    with open('/tmp/v7work.list', 'w', encoding='utf-8') as fh:
        for d in work:
            fh.write(d.replace('/music', '/media/Multimedia/Music', 1) + '\n')
    print('')
    print('   directories needing work: %d -> /tmp/v7work.list'
          % len(work))

    with open(outp, 'w') as fh:
        json.dump({'present': dict(present), 'total': dict(total),
                   'byext': {e: dict(c) for e, c in byext.items()},
                   'albums': {d: s for d, s in albums.items()},
                   'work_dirs': len(work)}, fh)
    print('wrote %s' % outp)


if __name__ == '__main__':
    main()
