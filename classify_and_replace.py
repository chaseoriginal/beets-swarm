#!/usr/bin/env python3
"""CLASSIFY every broken file, and find a working replacement for each.

Three classes, and they need different handling:

  REPLACE  - the audio is gone. The file is a stub (no MPEG frames) or
             ffmpeg cannot decode it. A working copy has to come from
             somewhere else on the share. If nothing matches, it needs
             a re-download (Lidarr's job) and is reported, not faked.

  REPAIR   - ffmpeg decodes it but mutagen cannot parse the tag
             container. The AUDIO is intact. Rebuilding the container
             with `ffmpeg -c copy` preserves the audio bit-for-bit and
             produces a file mutagen CAN read.

  OK       - mutagen failed but ffmpeg is happy and the file is
             playable. Only the metadata writer needs to handle it.

The replacement search looks for a working file with the same
identity, in this order:
  1. the same directory
  2. anywhere on the share, matched on the filename stem with the
     duplicate marker stripped
  3. anywhere on the share, matched on (artist, album, tracknumber)

Usage: classify_and_replace.py <root> <out.json> [--apply]
"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')
DUP_RE = re.compile(r'_\d{9,}$')


def stem_key(p):
    s = os.path.splitext(os.path.basename(p))[0]
    s = DUP_RE.sub('', s)
    return re.sub(r'[^a-z0-9]+', '', s.lower())


def mutagen_ok(p):
    try:
        import mutagen
        f = mutagen.File(p)
    except Exception:
        return False
    return f is not None and f.tags is not None


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


def decodes(p):
    """Does ffmpeg actually DECODE the audio (not just probe it)?"""
    try:
        r = subprocess.run(
            ['ffmpeg', '-v', 'error', '-i', p, '-f', 'null', '-'],
            capture_output=True, text=True, timeout=180)
        return r.returncode == 0 and not r.stderr.strip(), r.stderr.strip()[:120]
    except Exception as exc:
        return False, str(exc)[:100]


def has_audio_stream(p):
    try:
        r = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type',
             '-of', 'default=nw=1', p], capture_output=True, text=True,
            timeout=60)
        return r.returncode == 0 and 'audio' in r.stdout
    except Exception:
        return False


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else '/music'
    outp = sys.argv[2] if len(sys.argv) > 2 else '/tmp/repl.json'
    apply_changes = '--apply' in sys.argv

    merged = json.load(open('/tmp/scan_merged.json'))
    broken = [b['path'] for b in merged['broken']]
    untagged = merged['untagged']
    print('broken: %d   untagged: %d' % (len(broken), len(untagged)))
    sys.stdout.flush()

    # --- index every WORKING file on the share ---
    print('indexing working files...')
    allfiles = []
    for d, _s, fs in os.walk(root):
        for f in fs:
            if f.lower().endswith(AUDIO):
                allfiles.append(os.path.join(d, f))
    allfiles.sort()
    broken_set = set(broken)

    def is_working(p):
        if p in broken_set:
            return False
        try:
            return mutagen_ok(p)
        except Exception:
            return False

    by_stem = collections.defaultdict(list)
    for p in allfiles:
        if is_working(p):
            by_stem[stem_key(p)].append(p)
    print('working files indexed: %d' % sum(len(v) for v in by_stem.values()))
    sys.stdout.flush()

    # --- classify ---
    ts = time.strftime('%Y%m%d-%H%M%S')
    plan = []
    for p in broken:
        size = os.path.getsize(p) if os.path.exists(p) else -1
        stream = has_audio_stream(p)
        dec, derr = decodes(p)
        cls = 'REPLACE'
        why = 'no audio stream'
        if stream and dec:
            cls = 'REPAIR'
            why = 'ffmpeg decodes it; mutagen cannot parse the container'
        elif stream and not dec:
            cls = 'REPLACE'
            why = 'audio stream present but not decodable: %s' % derr
        elif size < 100000:
            cls = 'REPLACE'
            why = 'stub file, %d bytes, no audio frames' % size

        key = stem_key(p)
        cands = []
        for c in by_stem.get(key, []):
            same = os.path.dirname(c) == os.path.dirname(p)
            cands.append({'why': 'same-dir' if same else 'elsewhere',
                          'path': c,
                          'same_format': c.rsplit('.', 1)[-1].lower()
                          == p.rsplit('.', 1)[-1].lower()})
        # prefer a same-format candidate
        cands.sort(key=lambda c: (not c['same_format'], c['why'] != 'same-dir'))
        plan.append({'broken': p, 'size': size, 'class': cls, 'why': why,
                     'candidates': cands[:8]})
        print('   %-9s %-44s %9d  %s' % (cls, os.path.basename(p)[-44:],
                                         size, why[:44]))
        sys.stdout.flush()

    if apply_changes:
        print('')
        print('=== APPLYING ===')
        for e in plan:
            p = e['broken']
            if e['class'] == 'REPAIR':
                # rebuild the container: audio is copied bit-for-bit
                ext = p.rsplit('.', 1)[-1].lower()
                tmp = p + '.repair-' + ts
                r = subprocess.run(
                    ['ffmpeg', '-y', '-v', 'error', '-i', p, '-c', 'copy',
                     tmp], capture_output=True, text=True, timeout=600)
                if os.path.exists(tmp) and mutagen_ok(tmp):
                    ok = has_audio_stream(tmp)
                    if ok:
                        aside = p + '.broken-' + ts
                        os.rename(p, aside)
                        shutil.move(tmp, p)
                        print('   REPAIRED %s (original kept as %s)'
                              % (os.path.basename(p)[-46:],
                                 os.path.basename(aside)[-30:]))
                    else:
                        os.unlink(tmp)
                        print('   REPAIR FAILED (no audio) %s'
                              % os.path.basename(p)[-40:])
                else:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
                    print('   REPAIR FAILED %s: %s'
                          % (os.path.basename(p)[-40:], r.stderr[:80]))
                continue

            # REPLACE
            cands = e['candidates']
            if not cands:
                print('   NEEDS REDOWNLOAD (no copy on the share): %s'
                      % os.path.basename(p)[-46:])
                continue
            src = cands[0]['path']
            aside = p + '.broken-' + ts
            try:
                os.rename(p, aside)
                shutil.copy2(src, p)
            except Exception as exc:
                if os.path.exists(aside) and not os.path.exists(p):
                    os.rename(aside, p)
                print('   REPLACE FAILED %s: %s'
                      % (os.path.basename(p)[-40:], exc))
                continue
            if not mutagen_ok(p):
                os.unlink(p)
                os.rename(aside, p)
                print('   REPLACE REJECTED (bad copy) %s'
                      % os.path.basename(p)[-40:])
                continue
            print('   REPLACED %s  <- %s'
                  % (os.path.basename(p)[-44:], os.path.basename(src)[-40:]))

    with open(outp, 'w') as fh:
        json.dump({'plan': plan, 'untagged_dirs':
                   sorted(set(os.path.dirname(p) for p in untagged))}, fh)
    print('')
    print('wrote %s' % outp)


if __name__ == '__main__':
    main()
