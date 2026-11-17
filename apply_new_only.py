#!/usr/bin/env python3
"""Apply ONLY the replacements that have not been applied yet.

The plan file accumulates every resolved candidate, including the ones
already written to disk. A file is "already applied" when a
.broken-<timestamp> sibling exists next to it - so those are skipped
and only the genuinely new ones are written.

Usage: apply_new_only.py <plan.json>
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


def already_applied(path):
    d = os.path.dirname(path)
    stem = os.path.basename(path)
    try:
        for f in os.listdir(d):
            if f.startswith(stem + '.broken-'):
                return True
    except Exception:
        pass
    return False


def main():
    plan = json.load(open(sys.argv[1]))
    ts = time.strftime('%Y%m%d-%H%M%S')
    todo = [e for e in plan
            if e.get('resolved') and not already_applied(e['broken'])]
    print('=== %d new replacements to apply ===' % len(todo))
    counts = {'copied': 0, 'transcoded': 0, 'failed': 0}

    for e in todo:
        p = e['broken']
        src = e['resolved'][0]['path']
        base = os.path.basename(p)
        if not os.path.exists(src):
            print('   SKIP (source gone) %s' % base[-44:])
            counts['failed'] += 1
            continue
        if not (mutagen_ok(src) and has_audio(src)):
            print('   SKIP (bad source) %s' % base[-44:])
            counts['failed'] += 1
            continue
        sext = src.rsplit('.', 1)[-1].lower()
        bext = p.rsplit('.', 1)[-1].lower()
        aside = p + '.broken-' + ts
        try:
            os.rename(p, aside)
        except Exception as exc:
            print('   RENAME FAILED %s: %s' % (base[-32:], exc))
            counts['failed'] += 1
            continue
        ok = False
        how = ''
        try:
            if sext == bext:
                shutil.copy2(src, p)
                ok = True
                how = 'copy'
                counts['copied'] += 1
            else:
                ok, err = transcode(src, p, bext)
                if ok:
                    how = 'transcode %s->%s' % (sext, bext)
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
        print('   REPLACED %-42s %-20s <- %s'
              % (base[-42:], how, os.path.basename(src)[-28:]))

    print('')
    print('=== SUMMARY ===')
    for k, v in sorted(counts.items()):
        print('   %-12s %d' % (k, v))


if __name__ == '__main__':
    main()
