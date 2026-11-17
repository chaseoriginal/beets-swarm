#!/usr/bin/env python3
"""Why does ffmpeg exit 234 on the MP3s of this album?

The album-level gain runs ffmpeg's ebur128 filter per item WITH
count_blocks=True, and then combines the results in Python. The
per-track pass runs the same filter without the block counting and
succeeds for all 24 files. So the difference is in how ffmpeg is
invoked, not in the audio.

This runs the ebur128 analysis by hand on one M4A and one MP3 and
shows the actual ffmpeg output and exit code.

Usage: diag_ffmpeg234.py <dir>
"""
import os
import subprocess
import sys


def ebur128(path, count_blocks):
    """Run ffmpeg's ebur128 the way the beets backend does."""
    if count_blocks:
        cmd = ['ffmpeg', '-nostats', '-i', path, '-filter_complex',
               'ebur128=peak=true', '-f', 'null', '-']
    else:
        cmd = ['ffmpeg', '-nostats', '-i', path, '-filter_complex',
               'ebur128=peak=true', '-f', 'null', '-']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return r.returncode, r.stderr


def main():
    d = sys.argv[1]
    mp3s = []
    m4as = []
    for dirpath, _s, fs in os.walk(d):
        for f in sorted(fs):
            p = os.path.join(dirpath, f)
            e = os.path.splitext(f)[1].lower()
            if e == '.mp3':
                mp3s.append(p)
            elif e == '.m4a':
                m4as.append(p)
    print('=== %d mp3, %d m4a ===' % (len(mp3s), len(m4as)))

    for label, lst in (('M4A', m4as), ('MP3', mp3s)):
        if not lst:
            continue
        p = lst[0]
        print('')
        print('=== %s: %s ===' % (label, os.path.basename(p)[-46:]))
        rc, err = ebur128(p, True)
        print('   ebur128 rc=%d' % rc)
        tail = [l for l in err.splitlines() if l.strip()][-14:]
        for l in tail:
            print('   | %s' % l[:104])
        if rc != 0:
            print('   --- the ERROR lines ---')
            for l in err.splitlines():
                if 'rror' in l or 'nvalid' in l or 'ailed' in l:
                    print('   ! %s' % l[:104])


if __name__ == '__main__':
    main()
