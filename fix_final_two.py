#!/usr/bin/env python3
"""Fix the last two, correctly.

1. Static-X "10 Im With Stupid (Paul Barker Rmx).mp3"
   It was replaced with the BASE ALBUM track ("I'm With Stupid" from
   Wisconsin Death Trip) - a different recording. The real remix IS on
   the share:
     Static-X/Beneath… Between… Beyond… (2004)/
       Static-X - Beneath… Between… Beyond… - 10 - I'm With Stupid (Paul Barker remix).flac
   The earlier searches missed it because the filename and the tag both
   use a CURLY apostrophe ("I'm"), so an ASCII "im with stupid"
   substring search never matched.

2. Slipknot "14. Vermilion Pt.2(Bloodstone Mix) (Bonus track ).mp3"
   ffmpeg reads the AUDIO fine, but mutagen cannot parse the tag
   container. That is not a missing file - it is a broken ID3 header.
   The fix is to rebuild the container: read the audio stream with
   ffmpeg, write a fresh file, and copy the tags across.

Both are applied only after verification, and the previous file is kept
as a sidecar.

Usage: fix_final_two.py
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


def copy_tags(src, dst):
    """Copy the readable tags from src onto dst."""
    try:
        import mutagen
    except Exception:
        return False
    ext = dst.rsplit('.', 1)[-1].lower()
    sd = ff_tags(src)
    try:
        if ext == 'flac':
            from mutagen.flac import FLAC
            f = FLAC(dst)
            for k, v in sd.items():
                if k in ('artist', 'album', 'title', 'genre', 'date',
                         'tracknumber', 'discnumber', 'albumartist',
                         'composer'):
                    f[k] = [v]
            f.save()
        elif ext == 'mp3':
            from mutagen.id3 import ID3, TXXX
            try:
                id3 = ID3(dst)
            except Exception:
                id3 = ID3()
            for k, v in sd.items():
                if k in ('artist', 'album', 'title', 'genre', 'date',
                         'tracknumber', 'discnumber', 'albumartist',
                         'composer'):
                    f = {'tracknumber': 'TXXX:TRACKNUMBER'}.get(k, k)
                    id3.delall('TXXX:' + k)
                    id3.add(TXXX(encoding=3, desc=k, text=v))
            id3.save(dst, v2_version=3)
        else:
            return False
        return True
    except Exception as exc:
        print('   tag copy failed: %s' % exc)
        return False


def main():
    ts = time.strftime('%Y%m%d-%H%M%S')

    # ---- 1. Static-X: the correct remix ----
    sx = ('/music/General Music/Static‐X/(2004) [Beneath... Between... '
          'Beyond]/10 Im With Stupid (Paul Barker Rmx).mp3')
    remix = None
    for root, _s, fs in os.walk('/music/General Music/Static‐X'):
        for f in fs:
            if 'Stupid' not in f and 'stupid' not in f:
                continue
            p = os.path.join(root, f)
            if '.broken-' in f or '.wrong-' in f:
                continue
            d = ff_tags(p)
            t = nk(d.get('title', ''))
            if 'paulbarker' in t:
                remix = p
                break
        if remix:
            break
    print('=== 1. Static-X ===')
    print('   target: %s' % sx[-46:])
    if remix:
        print('   remix source: %s' % remix[-58:])
        rd = ff_tags(remix)
        print('   source tags: title=%r artist=%r album=%r'
              % (rd.get('title', ''), rd.get('artist', ''),
                 rd.get('album', '')))
        if mutagen_ok(remix) and has_audio(remix):
            aside = sx + '.wrong-' + ts
            os.rename(sx, aside)
            ok, how = False, ''
            try:
                ok, err = transcode(remix, sx, 'mp3')
                how = 'transcode flac->mp3' if ok else 'FAIL: %s' % err
            except Exception as exc:
                how = 'FAIL %s' % exc
            if ok and mutagen_ok(sx) and has_audio(sx):
                print('   CORRECTED %-16s <- %s' % (how, os.path.basename(remix)[-26:]))
                print('   the wrong copy kept as %s' % os.path.basename(aside))
            else:
                if os.path.exists(sx):
                    os.unlink(sx)
                os.rename(aside, sx)
                print('   REJECTED - restored')
        else:
            print('   source fails verification - skipping')
    else:
        print('   NO REMIX SOURCE FOUND')

    # ---- 2. Slipknot: rebuild the broken tag container ----
    sk = ('/music/General Music/Slipknot/(2008) All Hope Is Gone/'
          '14. Vermilion Pt.2(Bloodstone Mix) (Bonus track ).mp3')
    print('')
    print('=== 2. Slipknot ===')
    print('   target: %s' % sk[-46:])
    if not os.path.exists(sk):
        print('   TARGET MISSING')
    else:
        print('   mutagen reads it: %s' % mutagen_ok(sk))
        print('   ffmpeg reads it: %s' % has_audio(sk))
        if not mutagen_ok(sk) and has_audio(sk):
            d = ff_tags(sk)
            print('   tags ffmpeg can see: title=%r artist=%r album=%r'
                  % (d.get('title', ''), d.get('artist', ''),
                     d.get('album', '')))
            aside = sk + '.broken-' + ts
            tmp = '/tmp/slipknot-fix.mp3'
            os.rename(sk, aside)
            ok, err = transcode(aside, tmp, 'mp3')
            if ok:
                copy_tags(aside, tmp)
                shutil.move(tmp, sk)
                if mutagen_ok(sk) and has_audio(sk):
                    print('   REBUILT the tag container')
                    print('   the original kept as %s' % os.path.basename(aside))
                else:
                    os.unlink(sk)
                    os.rename(aside, sk)
                    print('   REJECTED - restored')
            else:
                os.rename(aside, sk)
                print('   TRANSCODE FAILED: %s' % err)
        elif mutagen_ok(sk):
            print('   already readable - nothing to do')


if __name__ == '__main__':
    main()
