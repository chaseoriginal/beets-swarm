#!/usr/bin/env python3
"""Count audio files missing a core tag (title, artist, album).

Uses mutagen, not ffprobe: mutagen reads only the file header, while
ffprobe spawns a process per file. Over CIFS that is the difference
between minutes and hours.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

AUDIO = ('.flac', '.mp3', '.m4a', '.ogg', '.aac', '.opus', '.wma')
BAD = ('', 'unknown', 'none', 'n/a', 'null', 'various',
       'various artists', 'track', 'title', 'album', 'artist', 'untitled')


def one(path):
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
    except Exception:
        return ('unreadable', path, [])
    if f is None or f.tags is None:
        return ('no_tags', path, ['title', 'artist', 'album'])
    miss = []
    for k in ('title', 'artist', 'album'):
        try:
            v = f.tags.get(k)
        except Exception:
            v = None
        if isinstance(v, list):
            v = v[0] if v else ''
        v = str(v or '').strip()
        if v.lower() in BAD:
            miss.append(k)
    return ('ok' if not miss else 'missing', path, miss)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else '/music'
    show = int(sys.argv[2]) if len(sys.argv) > 2 else 15

    files = []
    for dirpath, _d, fnames in os.walk(root):
        for f in fnames:
            if f.lower().endswith(AUDIO):
                files.append(os.path.join(dirpath, f))
    files.sort()
    print('   audio files: %d' % len(files))

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(one, files))

    tot = len(rows)
    miss = [r for r in rows if r[0] == 'missing']
    notags = [r for r in rows if r[0] == 'no_tags']
    unread = [r for r in rows if r[0] == 'unreadable']
    print('   complete:      %d' % (tot - len(miss) - len(notags) - len(unread)))
    print('   missing field: %d' % len(miss))
    print('   no tag block:  %d' % len(notags))
    print('   unreadable:    %d' % len(unread))
    for r in (miss + notags)[:show]:
        print('      %-54s %s' % (r[1][-54:], ','.join(r[2])))


if __name__ == '__main__':
    main()
