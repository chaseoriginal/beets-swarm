#!/usr/bin/env python3
"""Verify the mixed-format and damaged-file albums directly.

The SevenDust albums are the hard case: every track present as BOTH
.m4a and .mp3, and the .m4a files have corrupt AAC data. They failed
every pass until the runner was changed to:
  - compute the album gain PER FORMAT
  - run the FORCED per-track gain, which analyses each item alone

This reads the files back and reports, per format, how many carry a
complete set of analysis fields.

Usage: verify_mixed.py <dir> [<dir> ...]
"""
import os
import subprocess
import sys

AUDIO = ('.flac', '.mp3', '.m4a', '.mp4', '.ogg', '.opus', '.wma')


def analyse(p):
    o = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format_tags',
         '-of', 'default=nw=1', p], capture_output=True, text=True,
        timeout=90).stdout.splitlines()
    tags = {}
    for l in o:
        if '=' in l:
            k, v = l.split('=', 1)
            tags[k.split(':')[-1].strip().lower()] = v.strip()
    an = [k for k in tags if 'replaygain' in k or 'acoustid' in k]
    # does ffmpeg decode it cleanly?
    try:
        r = subprocess.run(
            ['ffmpeg', '-v', 'error', '-i', p, '-f', 'null', '-'],
            capture_output=True, text=True, timeout=240)
        err = r.stderr or ''
        damaged = any(x in err for x in ('Invalid data', 'Error while decoding',
                                         'Invalid packet'))
    except Exception:
        damaged = True
    return tags, an, damaged


def main():
    for d in sys.argv[1:]:
        print('')
        print('=== %s ===' % d)
        if not os.path.isdir(d):
            print('   MISSING')
            continue
        byext = {}
        for dirpath, _s, fs in os.walk(d):
            for f in sorted(fs):
                if not f.lower().endswith(AUDIO):
                    continue
                p = os.path.join(dirpath, f)
                e = os.path.splitext(f)[1].lower()
                tags, an, dmg = analyse(p)
                st = byext.setdefault(e, {'n': 0, 'full': 0, 'dmg': 0})
                st['n'] += 1
                if len(an) >= 4:
                    st['full'] += 1
                if dmg:
                    st['dmg'] += 1
                if len(an) < 4 and not dmg:
                    print('   BARE  an=%d %s' % (len(an), f[-46:]))
        for e in sorted(byext):
            s = byext[e]
            print('   %-6s %3d files, %3d fully tagged, %3d undecodable'
                  % (e, s['n'], s['full'], s['dmg']))
        tot = sum(s['n'] for s in byext.values())
        full = sum(s['full'] for s in byext.values())
        dmg = sum(s['dmg'] for s in byext.values())
        print('   TOTAL %d files, %d fully tagged, %d undecodable'
              % (tot, full, dmg))


if __name__ == '__main__':
    main()
