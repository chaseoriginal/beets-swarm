#!/usr/bin/env python3
"""Apply the final replacements, matching on the relaxed title rule
that the last7 search proved.

What the search found:
  Static-X  "10 Im With Stupid (Paul Barker Rmx).mp3"
      the good copy is tagged "I'm With Stupid (Paul Barker Rmx)" -
      a CURLY apostrophe, which the earlier normalisation missed
  Slipknot  "14. Vermilion Pt.2(Bloodstone Mix) (Bonus track ).mp3"
      the good copy is tagged "Vermilion Pt.2(Bloodstone Mix)"
      on "All Hope Is Gone"

The rule applied here: the candidate's title, with all non-alphanumerics
removed, must START WITH the broken file's title with the same
treatment, and the artist must match (article-insensitive).

The three that still have no candidate anywhere on the share:
  Lecrae "My Soul"
  Cure   "Homesick (Live)"
  Cure   "Untitled (Live)"
  Tool   "Sweat" (Escape from LA soundtrack)

Usage: apply_last.py
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


def title_variants(stem):
    out = []
    body = re.sub(r'^\d{1,3}\s*[.\-_]\s*', '', stem)
    body = re.sub(r'^\d{1,3}\s+', '', body)
    out.append(body)
    if ' - ' in body:
        out.append(body.split(' - ')[0].strip())
        out.append(body.split(' - ')[-1].strip())
    for p in [x.strip() for x in stem.split(' - ') if x.strip()]:
        if not re.fullmatch(r'\d{1,3}', p):
            out.append(p)
    b = re.sub(r'\s*\([^)]*\)\s*$', '', body).strip()
    out.append(b)
    if ' - ' in b:
        out.append(b.split(' - ')[0].strip())
    seen, res = set(), []
    for t in out:
        k = nk(t)
        if k and k not in seen:
            seen.add(k)
            res.append(t)
    return res


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
    left = []
    for e in plan:
        p = e['broken']
        try:
            if any(f.startswith(os.path.basename(p) + '.broken-')
                   for f in os.listdir(os.path.dirname(p))):
                continue
        except Exception:
            pass
        left.append(e)
    print('=== %d to place ===' % len(left))

    ts = time.strftime('%Y%m%d-%H%M%S')
    applied = 0
    for e in left:
        p = e['broken']
        tree = artist_tree(p)
        vs = title_variants(stem_of(p))
        keys = [nk(v) for v in vs if nk(v)]
        arts = {nk_artist(os.path.basename(tree))}
        for v in vs:
            if ' - ' in v:
                arts.add(nk_artist(v.split(' - ')[-1]))
                arts.add(nk_artist(v.split(' - ')[0]))
        cands = []
        seen = set()
        for dirpath, _s, fs in os.walk(tree):
            for f in fs:
                if not f.lower().endswith(AUDIO):
                    continue
                q = os.path.join(dirpath, f)
                if q in seen:
                    continue
                seen.add(q)
                d = ff_tags(q)
                t = nk(d.get('title', ''))
                if not t:
                    continue
                if not any(k and (t.startswith(k) or k.startswith(t))
                           for k in keys):
                    continue
                a = nk_artist(d.get('artist', ''))
                if a not in arts:
                    continue
                cands.append((q, d))
        if not cands:
            print('   NO CANDIDATE  %s' % os.path.basename(p)[-44:])
            continue
        # prefer the closest title
        def score(c):
            t = nk(c[1].get('title', ''))
            return min((abs(len(t) - len(k)) for k in keys
                        if t.startswith(k) or k.startswith(t)),
                       default=999)
        cands.sort(key=score)
        src, sd = cands[0]
        if not (mutagen_ok(src) and has_audio(src)):
            print('   BAD SOURCE  %s' % os.path.basename(p)[-44:])
            continue
        sext = src.rsplit('.', 1)[-1].lower()
        bext = p.rsplit('.', 1)[-1].lower()
        aside = p + '.broken-' + ts
        os.rename(p, aside)
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
                    print('   TRANSCODE FAILED %s: %s'
                          % (os.path.basename(p)[-30:], err))
        except Exception as exc:
            print('   COPY FAILED %s: %s' % (os.path.basename(p)[-30:], exc))
        if not ok or not (mutagen_ok(p) and has_audio(p)):
            if os.path.exists(p):
                os.unlink(p)
            os.rename(aside, p)
            print('   REJECTED (verify failed) %s - restored'
                  % os.path.basename(p)[-30:])
            continue
        applied += 1
        print('   REPLACED %-42s %-16s <- %s  (title=%r)'
              % (os.path.basename(p)[-42:], how,
                 os.path.basename(src)[-26:], sd.get('title', '')[:20]))
    print('')
    print('applied: %d' % applied)


if __name__ == '__main__':
    main()
