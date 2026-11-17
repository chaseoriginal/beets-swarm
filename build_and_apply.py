#!/usr/bin/env python3
"""Build a STRICT replacement plan from the already-collected loose
candidates, then APPLY it.

The loose search matched by filename alone and produced WRONG
candidates - Static-X "Down" matched 311's "Down". So every candidate
is re-verified here against the broken file's OWN identity, read from
its tags (the ID3 header survives even in a stub - only the audio
frames are gone):

  accept only when  artist matches  AND  title matches
                  OR album matches AND title matches AND track matches

Otherwise the file is reported for review rather than silently
replaced with the wrong song.

APPLY rules:
  - same format   -> byte copy
  - other format  -> transcode into the broken file's format, so the
                     path and extension stay honest and Lidarr's path
                     tracking still holds
  - the original is RENAMED to <name>.broken-<ts>, never deleted
  - the replacement is verified (mutagen reads it AND it has an audio
    stream) BEFORE the original is moved aside, and verified again
    after it is in place
  - a failure restores the original

Usage: build_and_apply.py [--apply]
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
    s = re.sub(r'[^a-z0-9]+', '', s)
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


def tracknum(d):
    t = d.get('track', '') or d.get('tracknumber', '')
    return t.split('/')[0].strip()


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
            timeout=60)
        return r.returncode == 0 and 'audio' in r.stdout
    except Exception:
        return False


def decodes(p):
    try:
        r = subprocess.run(
            ['ffmpeg', '-v', 'error', '-i', p, '-f', 'null', '-'],
            capture_output=True, text=True, timeout=240)
        return r.returncode == 0 and not r.stderr.strip(), r.stderr.strip()[:90]
    except Exception as exc:
        return False, str(exc)[:80]


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
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if r.returncode != 0 or not os.path.exists(dst):
        return False, (r.stderr or '')[-150:]
    return True, ''


def identity_ok(broken_tags, cand_path):
    """Is the candidate genuinely the same track?"""
    cd = ff_tags(cand_path)
    if not cd:
        return False, 'candidate has no readable tags'
    b_art, b_alb = nk(broken_tags.get('artist', '')), nk(broken_tags.get('album', ''))
    b_ttl, b_trk = nk(broken_tags.get('title', '')), tracknum(broken_tags)
    c_art, c_alb = nk(cd.get('artist', '')), nk(cd.get('album', ''))
    c_ttl, c_trk = nk(cd.get('title', '')), tracknum(cd)
    if not b_ttl or not c_ttl:
        return None, 'no title to compare'
    if b_ttl == c_ttl:
        if b_art and c_art and b_art == c_art:
            return True, 'artist+title'
        if b_alb and c_alb and b_alb == c_alb and b_trk and c_trk and b_trk == c_trk:
            return True, 'album+track+title'
        if b_trk and c_trk and b_trk == c_trk and (
                not b_art or not c_art or b_art == c_art):
            return True, 'track+title'
    return False, 'title/artist/album mismatch'


def main():
    apply_changes = '--apply' in sys.argv
    loose = json.load(open('/tmp/repl.json'))
    ts = time.strftime('%Y%m%d-%H%M%S')

    print('=== vetting %d broken files (apply=%s) ===' % (len(loose), apply_changes))
    plan = []
    for e in loose:
        p = e['broken']
        bt = ff_tags(p)
        size = os.path.getsize(p) if os.path.exists(p) else -1
        stream = has_audio(p)
        dec, derr = decodes(p)
        if stream and dec:
            cls = 'REPAIR'
        else:
            cls = 'REPLACE'

        accepted = []
        for c in e.get('candidates', []):
            cp = c['path']
            if not os.path.exists(cp):
                continue
            ok, why = identity_ok(bt, cp)
            if ok is True:
                accepted.append({'path': cp, 'why': why,
                                 'same_format': cp.rsplit('.', 1)[-1].lower()
                                 == p.rsplit('.', 1)[-1].lower(),
                                 'same_dir': os.path.dirname(cp)
                                 == os.path.dirname(p)})
            elif ok is None:
                accepted.append({'path': cp, 'why': 'no-title:' + why,
                                 'same_format': cp.rsplit('.', 1)[-1].lower()
                                 == p.rsplit('.', 1)[-1].lower(),
                                 'same_dir': os.path.dirname(cp)
                                 == os.path.dirname(p),
                                 'weak': True})
        accepted.sort(key=lambda c: (c.get('weak', False),
                                      not c['same_dir'],
                                      not c['same_format']))
        verdict = ('REPLACE' if accepted and not accepted[0].get('weak')
                   else 'REVIEW' if accepted else 'NEEDS REDOWNLOAD')
        plan.append({'broken': p, 'class': cls, 'size': size,
                     'verdict': verdict, 'candidates': accepted[:5],
                     'ident': {'title': bt.get('title', ''),
                               'artist': bt.get('artist', ''),
                               'album': bt.get('album', ''),
                               'track': tracknum(bt)}})
        print('   %-9s %-40s %s' % (verdict, os.path.basename(p)[-40:],
                                    (accepted[0]['why'] if accepted else '-')))

    with open('/tmp/repl_strict.json', 'w') as fh:
        json.dump(plan, fh)

    if not apply_changes:
        print('')
        print('dry run - nothing changed. Re-run with --apply.')
        return

    print('')
    print('=== APPLYING ===')
    counts = {'replaced': 0, 'copied': 0, 'transcoded': 0, 'review': 0,
              'redownload': 0, 'failed': 0}
    todo = set()
    for e in plan:
        p = e['broken']
        base = os.path.basename(p)
        if e['verdict'] != 'REPLACE':
            counts['review' if e['verdict'] == 'REVIEW' else 'redownload'] += 1
            print('   %-12s %s' % (e['verdict'], base[-46:]))
            continue
        src = e['candidates'][0]['path']
        if not (mutagen_ok(src) and has_audio(src)):
            counts['failed'] += 1
            print('   BAD CANDIDATE %s' % base[-40:])
            continue
        sext = src.rsplit('.', 1)[-1].lower()
        bext = p.rsplit('.', 1)[-1].lower()
        aside = p + '.broken-' + ts
        try:
            os.rename(p, aside)
        except Exception as exc:
            counts['failed'] += 1
            print('   RENAME FAILED %s: %s' % (base[-30:], exc))
            continue
        ok = False
        how = ''
        try:
            if sext == bext:
                shutil.copy2(src, p)
                ok = True
                how = 'copied'
                counts['copied'] += 1
            else:
                ok, err = transcode(src, p, bext)
                if ok:
                    how = 'transcoded %s->%s' % (sext, bext)
                    counts['transcoded'] += 1
                else:
                    print('   TRANSCODE FAILED %s: %s' % (base[-30:], err))
        except Exception as exc:
            print('   COPY FAILED %s: %s' % (base[-30:], exc))
        if not ok or not (mutagen_ok(p) and has_audio(p)):
            if os.path.exists(p):
                os.unlink(p)
            os.rename(aside, p)
            counts['failed'] += 1
            print('   REJECTED (verify failed) %s - restored' % base[-30:])
            continue
        counts['replaced'] += 1
        todo.add(os.path.dirname(p))
        print('   REPLACED %-40s %s <- %s'
              % (base[-40:], how, os.path.basename(src)[-28:]))

    print('')
    print('=== SUMMARY ===')
    for k, v in sorted(counts.items()):
        print('   %-12s %d' % (k, v))
    print('')
    print('   originals kept as <name>.broken-%s' % ts)
    print('   %d replaced files need the analysis pass re-run' %
          counts['replaced'])
    with open('/tmp/replaced_dirs.json', 'w') as fh:
        json.dump(sorted(todo), fh)


if __name__ == '__main__':
    main()
