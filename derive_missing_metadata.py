#!/usr/bin/env python3
"""Derive the missing core fields, including the two remaining cases:

  - a compilation ("Miscellaneous Tracks"): no sibling carries an album,
    and no single album is correct. The DIRECTORY NAME is the album.
  - a track whose album is only in the filename
    ("Tomorrow Never Comes - 10 - Prisoners Song.mp3" -> album
    "Tomorrow Never Comes"): take it from the filename's second field.

Rules, in order:
  1. TITLE: from the filename, minus the track-number prefix.
  2. ALBUM: from a sibling file that has one. If none has one, from the
     filename's album field ("Artist - Album - NN - Title"). If still
     nothing, from the DIRECTORY name - which is correct for a
     compilation folder.
  3. ARTIST: from a sibling's artist (ignoring "Various Artists"), else
     from the filename's artist field, else from the directory path.
  4. ALBUMARTIST: the artist.

Only fills an EMPTY or placeholder field. Never overwrites.

Usage: derive_missing_metadata.py <music-root> [--apply]
"""

import collections
import os
import re
import subprocess
import sys

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac')
PLACEHOLDER = ('', 'unknown', 'none', 'n/a', 'null', 'various',
               'various artists', 'track', 'title', 'album', 'artist',
               'untitled', 'tbd')

TRACK_PREFIX = re.compile(r'^\s*\d{1,3}\s*[-._ ]\s*')
# "Artist - Album - 01 - Title"
COMPACT = re.compile(
    r'^\s*(?P<artist>[^-]{1,60}?)\s+-\s+(?P<album>[^-]{1,80}?)\s+-\s+'
    r'(?P<track>\d{1,3})\s*-\s*(?P<title>.+)$')


def norm(v):
    return (v or '').strip()


def is_bad(v):
    return norm(v).lower() in PLACEHOLDER


def read_tags(path):
    o = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format_tags',
         '-of', 'default=nw=1', path],
        capture_output=True, text=True).stdout.splitlines()
    d = {}
    for l in o:
        if '=' in l:
            k, v = l.split('=', 1)
            d[k.split(':')[-1].strip().lower()] = v.strip()
    return d


def parse_filename(fn):
    """-> (artist, album, title) candidates from the filename."""
    stem = os.path.splitext(fn)[0]
    stem = TRACK_PREFIX.sub('', stem)
    m = COMPACT.match(stem)
    if m:
        return m.group('artist').strip(), m.group('album').strip(), \
            m.group('title').strip()
    if ' - ' in stem:
        parts = [p.strip() for p in stem.split(' - ')]
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        if len(parts) == 2:
            return '', '', parts[1]
    return '', '', stem.strip()


def dir_album_hint(dirpath):
    """The album named by the directory, and the artist."""
    p = dirpath.replace('/music/', '').replace('/tmp/dmtest/', '')
    parts = [x for x in p.split('/') if x]
    artist = album = ''
    if len(parts) >= 3 and parts[0] in ('General Music', 'Christian Music'):
        artist = parts[1].strip()
        album = parts[2].strip()
    elif len(parts) >= 1:
        album = parts[-1].strip()
    # strip a leading "(year) " decoration from the album folder
    album = re.sub(r'^\(\d{4}\)\s*', '', album).strip()
    return artist, album


def write_tags(path, fixes):
    ext = path.rsplit('.', 1)[-1].lower()
    try:
        if ext == 'flac':
            from mutagen.flac import FLAC
            f = FLAC(path)
            for k, v in fixes.items():
                f[k] = [v]
            f.save()
        elif ext == 'mp3':
            from mutagen.id3 import ID3, TXXX
            try:
                id3 = ID3(path)
            except Exception:
                id3 = ID3()
            for k, v in fixes.items():
                id3.delall('TXXX:' + k)
                id3.add(TXXX(encoding=3, desc=k, text=v))
            id3.save(path, v2_version=3)
        elif ext in ('m4a', 'mp4'):
            from mutagen.mp4 import MP4, MP4FreeForm
            f = MP4(path)
            for k, v in fixes.items():
                f[k] = [MP4FreeForm(k.encode('utf-8'), v.encode('utf-8'))]
            f.save()
        else:
            return False, 'unsupported format'
        return True, ''
    except Exception as exc:
        return False, str(exc)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    apply_changes = '--apply' in sys.argv
    root = args[0] if args else '/music'

    dirs = []
    for dirpath, _d, files in os.walk(root):
        aud = [f for f in files if f.lower().endswith(AUDIO)]
        if aud:
            dirs.append((dirpath, aud))
    dirs.sort()

    print('scanning %d album dirs (apply=%s)' % (len(dirs), apply_changes))
    fields_set = collections.Counter()
    fixed_files = 0
    touched_dirs = 0
    broken = []

    for dirpath, aud in dirs:
        rows = [(f, read_tags(os.path.join(dirpath, f))) for f in sorted(aud)]

        album_vals = collections.Counter()
        artist_vals = collections.Counter()
        for f, t in rows:
            if not is_bad(t.get('album', '')):
                album_vals[norm(t.get('album'))] += 1
            if not is_bad(t.get('artist', '')) and \
                    norm(t.get('artist')).lower() != 'various artists':
                artist_vals[norm(t.get('artist'))] += 1

        common_album = album_vals.most_common(1)[0][0] if album_vals else ''
        common_artist = artist_vals.most_common(1)[0][0] if artist_vals else ''
        dir_artist, dir_album = dir_album_hint(dirpath)
        if not common_artist:
            common_artist = dir_artist

        for f, t in rows:
            fa, falb, fttl = parse_filename(f)
            fixes = {}
            if is_bad(t.get('title', '')) and fttl:
                fixes['title'] = fttl
            if is_bad(t.get('album', '')):
                if common_album:
                    fixes['album'] = common_album
                elif falb:
                    fixes['album'] = falb
                elif dir_album:
                    fixes['album'] = dir_album
            if is_bad(t.get('artist', '')):
                if common_artist:
                    fixes['artist'] = common_artist
                elif fa:
                    fixes['artist'] = fa
            if is_bad(t.get('albumartist', '')) and common_artist:
                fixes['albumartist'] = common_artist
            if not fixes:
                continue
            touched_dirs += 1
            p = os.path.join(dirpath, f)
            ok, err = write_tags(p, fixes)
            if not ok:
                broken.append((p, err))
                continue
            fixed_files += 1
            for k in fixes:
                fields_set[k] += 1

    print('')
    print('=== RESULT ===')
    print('  dirs touched:  %d' % touched_dirs)
    print('  files fixed:   %d' % fixed_files)
    for k, v in sorted(fields_set.items()):
        print('    %-14s %d' % (k, v))
    print('  UNWRITABLE:    %d' % len(broken))
    for p, err in broken[:12]:
        print('    %-52s %s' % (p[-52:], err[:40]))


if __name__ == '__main__':
    main()
