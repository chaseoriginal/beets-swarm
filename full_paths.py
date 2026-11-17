#!/usr/bin/env python3
"""Full paths for every file that could serve the remaining targets.

The earlier searches filtered on the FILENAME, which missed files with
a curly apostrophe ("I'm With Stupid"). This one searches the TAGS and
prints the FULL path, so nothing is hidden by a truncated name.

Targets:
  Static-X "Im With Stupid (Paul Barker Rmx)"  - the remix
  Slipknot "Vermilion Pt.2(Bloodstone Mix)"
  Cure     "Homesick (Live)" / "Untitled (Live)"
  Lecrae   "My Soul"
  Tool     "Sweat" (Escape from LA)

Usage: full_paths.py
"""
import os
import re
import subprocess
import unicodedata

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')


def nk(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace('&', 'and')
    return ''.join(ch for ch in s if ch.isalnum())


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


def has_audio(p):
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type',
             '-of', 'default=nw=1', p], capture_output=True, text=True,
            timeout=60)
        return r.returncode == 0 and 'audio' in r.stdout
    except Exception:
        return False


TARGETS = {
    'staticx': ['imwithstupid'],
    'slipknot': ['vermilionpt2', 'vermilionpt2bloodstone'],
    'cure': ['homesick', 'untitledlive'],
    'lecrae': ['mysoul'],
    'tool': ['sweat'],
}

# the artist tree each target belongs to
TREES = {
    'staticx': '/music/General Music/Static‐X',
    'slipknot': '/music/General Music/Slipknot',
    'cure': '/music/General Music/Cure, The',
    'lecrae': '/music/Christian Music/Lecrae',
    'tool': '/music/General Music/SoundTracks/Escape from LA [Soundtrack]  (1996)',
}


def main():
    for key, trees in TREES.items():
        print('')
        print('=== %s : %s ===' % (key, trees[-46:]))
        if not os.path.isdir(trees):
            print('   TREE MISSING')
            continue
        hits = []
        for dirpath, _s, fs in os.walk(trees):
            for f in fs:
                if not f.lower().endswith(AUDIO):
                    continue
                p = os.path.join(dirpath, f)
                d = ff_tags(p)
                t = nk(d.get('title', ''))
                if not t:
                    continue
                if not any(w in t for w in TARGETS[key]):
                    continue
                hits.append((p, d))
        print('   %d title matches' % len(hits))
        for p, d in hits:
            side = ' [sidecar]' if ('.broken-' in p or '.wrong-' in p) else ''
            au = 'OK' if has_audio(p) else 'NO-AUDIO'
            print('   %-6s %s' % (au, p))
            print('          title=%r artist=%r album=%r%s'
                  % (d.get('title', '')[:40], d.get('artist', '')[:26],
                     d.get('album', '')[:28], side))


if __name__ == '__main__':
    main()
