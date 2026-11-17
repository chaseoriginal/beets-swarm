#!/usr/bin/env python3
"""APPLY the resolved replacements.

Takes the plan from resolve_final.py, where the RESOLVED candidates are
in the 'resolved' key, and puts them in place.

Rules:
  - the candidate must be readable by mutagen AND have an audio stream
  - the ORIGINAL is RENAMED to <name>.broken-<ts>, never deleted
  - a candidate in a different format is TRANSCODED into the broken
    file's format, so the path and extension stay honest and Lidarr's
    path tracking still holds
  - the replacement is verified BEFORE the original is moved aside, and
    verified again after it is in place
  - any failure restores the original

Usage: apply_resolved.py <plan.json> [--apply]
"""
import json
import os
import shutil
import subprocess
import sys
import time


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


def ff_tags(p):
    o = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format_tags',
         '-of', 'default=nw=1', p], capture_output=True, text=True,
        timeout=60).stdout.splitlines()
    d = {}
    for l in o:
        if '=' in l:
            k, v = l.split('=', 1)
            d[k.split(':')[-1].strip().lower()] = v.strip()
    return d


def main():
    plan = json.load(open(sys.argv[1]))
    do_apply = '--apply' in sys.argv
    ts = time.strftime('%Y%m%d-%H%M%S')

    todo = [e for e in plan if e.get('resolved')]
    print('=== %d resolved replacements, apply=%s ===' % (len(todo), do_apply))
    counts = {'copied': 0, 'transcoded': 0, 'failed': 0, 'skipped': 0}
    dirs = set()

    for e in todo:
        p = e['broken']
        c = e['resolved'][0]
        src = c['path']
        base = os.path.basename(p)
        if not os.path.exists(src):
            counts['skipped'] += 1
            print('   SKIP (source gone) %s' % base[-44:])
            continue
        if not (mutagen_ok(src) and has_audio(src)):
            counts['skipped'] += 1
            print('   SKIP (bad source) %s' % base[-44:])
            continue
        sext = src.rsplit('.', 1)[-1].lower()
        bext = p.rsplit('.', 1)[-1].lower()
        how = 'copy' if sext == bext else 'transcode %s->%s' % (sext, bext)

        if not do_apply:
            print('   WOULD %-24s %-42s <- %s'
                  % (how, base[-42:], os.path.basename(src)[-28:]))
            continue

        aside = p + '.broken-' + ts
        try:
            os.rename(p, aside)
        except Exception as exc:
            counts['failed'] += 1
            print('   RENAME FAILED %s: %s' % (base[-32:], exc))
            continue
        ok = False
        try:
            if sext == bext:
                shutil.copy2(src, p)
                ok = True
                counts['copied'] += 1
            else:
                ok, err = transcode(src, p, bext)
                if ok:
                    counts['transcoded'] += 1
                else:
                    print('   TRANSCODE FAILED %s: %s' % (base[-32:], err))
        except Exception as exc:
            print('   COPY FAILED %s: %s' % (base[-32:], exc))
        if not ok or not (mutagen_ok(p) and has_audio(p)):
            if os.path.exists(p):
                os.unlink(p)
            os.rename(aside, p)
            counts['failed'] += 1
            print('   REJECTED (verify failed) %s - restored' % base[-32:])
            continue
        dirs.add(os.path.dirname(p))
        print('   REPLACED %-42s %-22s <- %s'
              % (base[-42:], how, os.path.basename(src)[-26:]))

    print('')
    print('=== SUMMARY ===')
    for k, v in sorted(counts.items()):
        print('   %-12s %d' % (k, v))
    if do_apply:
        print('')
        print('   originals kept as <name>.broken-%s' % ts)
        print('   %d directories need the analysis pass re-run' % len(dirs))
        with open('/tmp/replaced_dirs.json', 'w') as fh:
            json.dump(sorted(dirs), fh)


if __name__ == '__main__':
    main()
