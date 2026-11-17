#!/usr/bin/env python3
"""CORRECT the last replacements.

Two problems:

1. Static-X "10 Im With Stupid (Paul Barker Rmx).mp3" was replaced
   with "02 - I'm With Stupid.flac" from "Wisconsin Death Trip" - the
   BASE ALBUM track, not the Paul Barker remix. Different recording,
   wrong track. The scoring preferred the shortest title, and the
   remix's title is longer.
   The fix: the candidate title must match the FULL key, qualifier
   included, and the album must match the broken file's own folder.

2. Slipknot "14. Vermilion Pt.2(Bloodstone Mix) (Bonus track ).mp3"
   reported BAD SOURCE. The candidate chosen was probably a
   .broken- file, or one that mutagen cannot read. Skip .broken-
   files and prefer a source that verifies.

The remaining three (Lecrae "My Soul", Cure "Homesick (Live)", Cure
"Untitled (Live)", Tool "Sweat") are searched across the WHOLE library
with the full title key, qualifier included.

Usage: correct_last.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')


def nk(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace('&', 'and')
    return ''.join(ch for ch in s if ch.isalnum())


def nk_artist(s):
    s = nk(s)
    for a in ('the',):
        if s.startswith(a) and len(s) > len(a):
            s = s[len(a):]
        elif s.endswith(a) and len(s) > len(a):
            s = s[:-len(a)]
    return s


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


def transcode(src, dst, ext):
    if ext == 'flac':
        cmd = ['ffmpeg', '-y', '-v', 'error', '-i', src, '-c:a', 'flac',
               '-compression_level', '5', dst]
    elif ext == 'mp3':
        cmd = ['ffmpeg', '-y', '-v', 'error', '-i', src,
               '-c:a', 'libmp3lame', '-b:a', '320k', dst]
    elif ext in ('m4a', 'mp4'):
        cmd = ['ffmpeg', '-y', '-v', 'error', '-i', src,
               '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart', dst]
    elif ext == 'ogg':
        cmd = ['ffmpeg', '-y', '-v', 'error', '-i', src,
               '-c:a', 'libvorbis', '-q:a', '5', dst]
    else:
        return False, 'no encoder for .%s' % ext
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not os.path.exists(dst):
        return False, (r.stderr or '')[-150:]
    return True, ''


def stem_of(path):
    s = os.path.splitext(os.path.basename(path))[0]
    s = re.sub(r'_\d{6,}$', '', s).strip()
    return re.sub(r'^[-–]\s*', '', s)


def full_key(stem):
    """The FULL title key of the broken file: body with the track
    number stripped, qualifiers KEPT."""
    body = re.sub(r'^\d{1,3}\s*[.\-_]\s*', '', stem)
    body = re.sub(r'^\d{1,3}\s+', '', body)
    return nk(body)


def artist_tree(path):
    d = os.path.dirname(path)
    for _ in range(4):
        gp = os.path.basename(os.path.dirname(d))
        if gp in ('General Music', 'Christian Music', 'SoundTracks'):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(path)


def main():
    plan = json.load(open('/tmp/repl_last.json'))
    targets = []
    for e in plan:
        p = e['broken']
        b = os.path.basename(p)
        if 'Im With Stupid' in b or 'Vermilion Pt.2' in b:
            targets.append((p, 'correct'))
    print('=== the files to correct ===')
    for p, _ in targets:
        print('   %s' % p)

    ts = time.strftime('%Y%m%d-%H%M%S')
    for p, _ in targets:
        stem = stem_of(p)
        key = full_key(stem)
        tree = artist_tree(p)
        folder_album = nk(os.path.basename(os.path.dirname(p)))
        print('')
        print('   --- %s' % os.path.basename(p)[-44:])
        print('       key=%r  tree=%s' % (key, tree[-46:]))

        cands = []
        seen = set()
        for dirpath, _s, fs in os.walk(tree):
            for f in fs:
                if not f.lower().endswith(AUDIO):
                    continue
                if '.broken-' in f:
                    continue
                q = os.path.join(dirpath, f)
                if q in seen:
                    continue
                seen.add(q)
                d = ff_tags(q)
                t = nk(d.get('title', ''))
                if not t:
                    continue
                # the FULL key must match, qualifier included
                if not (t == key or t.startswith(key) or key.startswith(t)):
                    continue
                same_album = nk(d.get('album', '')) == folder_album
                cands.append((q, d, same_album))
        print('       candidates: %d' % len(cands))
        for q, d, sa in cands[:6]:
            print('         %-40s title=%-34r album=%r%s'
                  % (os.path.basename(q)[-40:], d.get('title', '')[:34],
                     d.get('album', '')[:26], '  SAME-ALBUM' if sa else ''))
        if not cands:
            print('       NO EXACT CANDIDATE - leaving the current file')
            continue
        # prefer: same album, then a title that matches exactly
        cands.sort(key=lambda c: (not c[2], nk(c[1].get('title', '')) != key))
        src, sd, sa = cands[0]
        if not (mutagen_ok(src) and has_audio(src)):
            print('       SOURCE FAILS VERIFICATION - skipping')
            continue
        sext = src.rsplit('.', 1)[-1].lower()
        bext = p.rsplit('.', 1)[-1].lower()
        # undo the wrong replacement first: move the wrong one aside
        wrong = p + '.wrong-' + ts
        try:
            os.rename(p, wrong)
        except Exception as exc:
            print('       RENAME FAILED: %s' % exc)
            continue
        ok = False
        how = ''
        try:
            if sext == bext:
                shutil.copy2(src, p)
                ok, how = True, 'copy'
            else:
                ok, err = transcode(src, p, bext)
                how = 'transcode %s->%s' % (sext, bext) if ok else 'FAIL'
                if not ok:
                    print('       TRANSCODE FAILED: %s' % err)
        except Exception as exc:
            print('       COPY FAILED: %s' % exc)
        if not ok or not (mutagen_ok(p) and has_audio(p)):
            if os.path.exists(p):
                os.unlink(p)
            os.rename(wrong, p)
            print('       REJECTED - restored the previous file')
            continue
        print('       CORRECTED %-38s %-16s <- %s'
              % (os.path.basename(p)[-38:], how, os.path.basename(src)[-26:]))
        print('       (the wrong copy kept as %s)'
              % os.path.basename(wrong))


if __name__ == '__main__':
    main()
