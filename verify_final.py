#!/usr/bin/env python3
"""FINAL verification of every file that was replaced or repaired.

Reads each one back and reports:
  - mutagen can read it
  - it has an audio stream
  - the analysis fields it carries
  - its title / artist / album

Usage: verify_final.py
"""
import json
import os
import subprocess

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')


def ff_tags(p):
    try:
        o = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format_tags',
             '-of', 'default=nw=1', p], capture_output=True, text=True,
            timeout=60).stdout.splitlines()
    except Exception:
        return {}
    d = {}
    for l in o:
        if '=' in l:
            k, v = l.split('=', 1)
            d[k.split(':')[-1].strip().lower()] = v.strip()
    return d


def mutagen_ok(p):
    try:
        import mutagen
        f = mutagen.File(p)
    except Exception:
        return False
    return f is not None and f.tags is not None


def has_audio(p):
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type',
             '-of', 'default=nw=1', p], capture_output=True, text=True,
            timeout=90)
        return r.returncode == 0 and 'audio' in r.stdout
    except Exception:
        return False


def main():
    # find every sidecar and check the file it was made from
    fixed = []
    broken = []
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if '.broken-' in f or '.wrong-' in f:
                broken.append(os.path.join(root, f))
                orig = os.path.join(root, f.split('.broken-')[0]
                                    .split('.wrong-')[0])
                fixed.append(orig)
    fixed = sorted(set(fixed))
    print('=== %d files were replaced or repaired ===' % len(fixed))
    ok = bad = 0
    for p in fixed:
        if not os.path.exists(p):
            print('   MISSING %s' % p[-50:])
            bad += 1
            continue
        mu = mutagen_ok(p)
        au = has_audio(p)
        d = ff_tags(p)
        an = len([k for k in d if 'replaygain' in k.lower()
                  or 'acoustid' in k.lower()])
        good = mu and au
        if good:
            ok += 1
        else:
            bad += 1
        print('   %-4s mutagen=%-5s audio=%-5s an=%d  %-46s'
              % ('OK' if good else 'BAD', mu, au, an,
                 os.path.basename(p)[-46:]))
        print('        title=%r artist=%r album=%r'
              % (d.get('title', '')[:34], d.get('artist', '')[:24],
                 d.get('album', '')[:26]))
    print('')
    print('   readable with audio: %d    still broken: %d' % (ok, bad))
    print('   sidecars kept: %d' % len(broken))

    # anything still unreadable anywhere in the library?
    print('')
    print('=== a full sweep for anything still unreadable ===')
    n = 0
    for root, _s, fs in os.walk('/music'):
        for f in fs:
            if not f.lower().endswith(AUDIO):
                continue
            if '.broken-' in f or '.wrong-' in f:
                continue
            p = os.path.join(root, f)
            if not (mutagen_ok(p) and has_audio(p)):
                n += 1
                if n <= 25:
                    print('   %-52s mutagen=%s audio=%s'
                          % (p[-52:], mutagen_ok(p), has_audio(p)))
    print('   STILL UNREADABLE: %d' % n)


if __name__ == '__main__':
    main()
