#!/usr/bin/env python3
"""
addlyrics - put synced lyrics into MP3 files you already have.

You supply the audio (download it however you like). This finds the lyrics, writes them
into the file's own lyrics tag, and drops a .lrc sidecar next to it for timed display.

    song.mp3  +  optional YouTube link  ->  lyrics inside song.mp3  +  song.lrc

Usage:
    python3 addlyrics.py song.mp3 --link "https://youtu.be/XXXXXXXXXXX"
    python3 addlyrics.py song.mp3                        # from the file's own tags
    python3 addlyrics.py song.mp3 --artist "X" --title "Y"
    python3 addlyrics.py *.mp3                           # batch, tags only
    python3 addlyrics.py song.mp3 --dry-run              # show the match, change nothing

Requires: ffmpeg on PATH. yt-dlp only if you pass --link (and it is never fatal if it
fails or is missing - the file's own tags are used instead).

Where the artist/title come from, in order of preference:
    1. --artist / --title / --album if you passed them
    2. the --link's own metadata (cleanest for YouTube rips)
    3. the filename, if it looks like "Artist - Title.mp3"
    4. the file's embedded tags
    5. title-only, as a last resort (reported as such, because it is the least certain)
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from yt2mp3lrc import (DURATION_TOLERANCE, clean_track_name, embed_lyrics, find_lyrics,
                       has_embedded_lyrics, split_artist_track, strip_lrc_timestamps)

AUDIO_EXT = ".mp3"

# Title-only matching is the risky one: two unrelated songs can share a title AND a duration
# (TheFatRat "Xenogenesis" 233s vs 3TEETH "Xenogenesis" 233s). So it is only allowed when we have
# no artist to check against at all, and then only with a tighter duration window.
TITLE_ONLY_TOLERANCE = 2

# Uploader names that are channels/labels, not artists. When a tag's artist looks like one of
# these we treat it as unusable rather than trusting it.
CHANNEL_WORDS = ("music", "records", "record", "topic", "official", "entertainment",
                 "media", "vibes", "sounds", "sound", "lyrics", "audio", "label", "fm")


def looks_like_channel(name):
    """Heuristic: is this tag an uploader channel rather than the artist?

    "ANN MUSIC", "7CLOUDS", "Trap Nation", "X - Topic" are channels. Trusting them as the
    artist makes the artist guard reject the real record, so they are dropped instead.
    """
    n = (name or "").strip().lower()
    if not n:
        return True
    if n.isupper() and len(n) > 6:                     # ANN MUSIC, 7CLOUDS, LOFI GIRL
        return True
    return any(word in n for word in CHANNEL_WORDS)


def is_distinctive(title):
    """Is this title specific enough to search on with no artist to check against?

    "Xenogenesis" or "Let Me Down Slowly" yes; "G", "Intro", "Track 1" no.
    """
    words = [w for w in re.sub(r"[^\w\s]", " ", (title or "").lower()).split() if len(w) > 2]
    return len(words) >= 2 or (len(words) == 1 and len(words[0]) >= 6)


# ---------------------------------------------------------------- reading the file


def probe(path):
    """Duration and tags read straight out of the file with ffprobe (no extra dependency)."""
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "format=duration:format_tags=title,artist,album,album_artist",
           "-of", "json", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe could not read {path.name}: {r.stderr.strip()[:120]}")
    fmt = (json.loads(r.stdout or "{}") or {}).get("format", {})
    tags = {k.lower(): (v or "") for k, v in (fmt.get("tags") or {}).items()}
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = None
    return {
        "duration": duration,
        "title": tags.get("title", ""),
        "artist": tags.get("artist") or tags.get("album_artist") or "",
        "album": tags.get("album", ""),
    }


def link_metadata(url):
    """Metadata from the link. Never fatal: on any failure we fall back to tags."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print("   ! yt-dlp isn't installed, so --link can't be read - using the file's tags")
        return None
    try:
        with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        first = str(e).splitlines()[0][:140] if str(e) else "unknown error"
        print(f"   ! couldn't read that link ({first})")
        print("     falling back to the file's own tags")
        return None


def from_filename(path):
    """"Alan Walker - Faded.mp3" -> ("Alan Walker", "Faded").

    Only when the stem really looks like "Artist - Title". A stem that doesn't (e.g. "G.mp3")
    yields nothing - turning an arbitrary filename into a search query is how you end up
    matching some unrelated song.
    """
    stem = path.stem
    if " - " not in stem:
        return None
    left, right = stem.split(" - ", 1)
    if not left.strip() or len(left) > 40:      # probably a title with a dash in it
        return None
    if not right.strip():
        return None
    return left.strip(), clean_track_name(right), ""


def candidates(probed, info, args, path):
    """Ordered (artist, track, album) guesses to try against LRCLIB. First hit wins.

    Every guess except the last one carries an artist, because the artist guard is what stops
    a same-title/same-duration song from the wrong artist being matched. The title-only guess is
    allowed only when nothing gave us an artist at all.
    """
    guessed = []

    if args.artist or args.title:                                     # 1. explicit flags
        guessed.append((args.artist or "", args.title or "", args.album or ""))

    if info:                                                          # 2. the link
        artist, track, album = split_artist_track(info)
        guessed.append((artist, track, args.album or album))
        cleaned = clean_track_name(info.get("title") or "")
        if cleaned:
            guessed.append((artist, cleaned, args.album or album))

    tag_artist, tag_title = probed["artist"], probed["title"]         # 3. the file's tags
    tag_artist_usable = tag_artist and not looks_like_channel(tag_artist)
    if tag_artist_usable:
        guessed.append((tag_artist, tag_title, probed["album"]))
    elif tag_title and " - " in tag_title:
        # channel-style artist, but the title is itself "Artist - Track"
        left, right = tag_title.split(" - ", 1)
        guessed.append((left.strip(), clean_track_name(right), probed["album"]))
    if tag_title:
        guessed.append((tag_artist if tag_artist_usable else "", tag_title, probed["album"]))

    name_guess = from_filename(path)                                  # 4. the filename
    if name_guess:
        guessed.append((name_guess[0], name_guess[1], probed["album"]))

    # de-duplicate, keeping order and dropping empty guesses
    seen, unique = set(), []
    for cand in guessed:
        key = tuple((x or "").strip().lower() for x in cand)
        if key in seen or not key[1]:
            continue
        seen.add(key)
        unique.append(cand)

    # 5. title-only, last and only if no artist was available anywhere
    if not any(artist for artist, _, _ in unique):
        for _, title, _ in list(unique) + [(("", tag_title, ""))]:
            if title and is_distinctive(title):
                unique.append(("", title, ""))
                break

    return unique


# ---------------------------------------------------------------- per-file flow


def attach(path, args):
    """Returns one of: 'ok', 'have', 'none', 'failed'."""
    print(f"-> {path.name}")

    if path.suffix.lower() != AUDIO_EXT:
        print(f"   ! only {AUDIO_EXT} is supported (got {path.suffix})")
        return "failed"

    probed = probe(path)
    dur = probed["duration"]
    lrc = path.with_suffix(".lrc")
    print(f"   {dur:.0f}s | tags: {probed['artist'] or '?'} / {probed['title'] or '?'}")

    if lrc.exists() and not args.force:
        print("   = .lrc already present, skipping (use --force to redo)")
        return "have"

    info = link_metadata(args.link) if args.link else None
    duration = dur or (info or {}).get("duration")

    found = None
    tried = []
    used = None
    for artist, track, album in candidates(probed, info, args, path):
        if not track:
            continue
        tried.append(f"{artist or '?'} / {track}")
        # With no artist to check against, only a near-exact duration will do.
        tolerance = DURATION_TOLERANCE if artist else TITLE_ONLY_TOLERANCE
        found = find_lyrics(artist, track, album, duration, tolerance)
        if found:
            used = (artist, track)
            break

    if not found:
        if not tried:
            print("   - nothing to search with: no tags, and the filename isn't 'Artist - Title.mp3'")
            print("     give me something to go on: --artist/--title, or --link")
            return "none"
        print(f"   - no lyrics found in LRCLIB. tried {len(tried)} guess(es):")
        for t in tried:
            print(f"       {t}")
        print("     hint: pass --artist/--title (and --link if you have it) to pin it down.")
        print("           if the artist tag is a channel name, the guess list above is why.")
        return "none"

    print(f"   match: {found['source']}")
    if not used[0]:
        print("   ! MATCHED ON THE TITLE ALONE - verify this is really the right song")

    text = found["plain"] or strip_lrc_timestamps(found["synced"] or "")
    if args.dry_run:
        print(f"   (dry run) would embed {len(text.splitlines())} lines"
              f"{'; would write ' + lrc.name if found['synced'] else '; no sidecar (plain only)'}")
        for line in text.splitlines()[:2]:
            print(f"       {line}")
        return "ok"

    if found["synced"] and not args.no_sidecar:
        lrc.write_text(found["synced"], encoding="utf-8")
        print(f"   + {lrc.name}  (synced, {len(found['synced'].splitlines())} lines)")

    if not args.no_embed:
        if has_embedded_lyrics(path) and not args.force:
            print("   = lyrics already in the file")
        else:
            embed_lyrics(path, text)
            print(f"   + lyrics embedded into {path.name}  ({len(text.splitlines())} lines)")

    return "ok"


def main():
    ap = argparse.ArgumentParser(
        description="Attach synced lyrics to MP3 files you already have.",
        epilog="Lyrics come from LRCLIB (lrclib.net). Only the lyrics and tags are touched - "
               "the audio is copied bit-for-bit.")
    ap.add_argument("files", nargs="+", help="mp3 file(s) to attach lyrics to")
    ap.add_argument("--link", metavar="URL",
                    help="the link you got the audio from (YouTube etc). Optional; only used to "
                         "get better artist/title than the file's tags. Needs yt-dlp.")
    ap.add_argument("--artist", help="override the artist")
    ap.add_argument("--title", help="override the title")
    ap.add_argument("--album", help="override the album")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be matched, change nothing")
    ap.add_argument("--force", action="store_true", help="redo files that already have lyrics")
    ap.add_argument("--no-embed", action="store_true", help="write only the .lrc sidecar")
    ap.add_argument("--no-sidecar", action="store_true",
                    help="embed only - no .lrc file, strictly one file per song")
    args = ap.parse_args()

    if args.link and len(args.files) > 1:
        ap.error("--link applies to a single file. Run once per file, or drop --link "
                 "and let each file's own tags/filename do the work.")

    paths = []
    for f in args.files:
        p = Path(f)
        if p.is_dir():
            found = sorted(x for x in p.iterdir() if x.suffix.lower() == AUDIO_EXT)
            print(f"# {p} -> {len(found)} mp3 file(s)")
            paths += found
        else:
            paths.append(p)

    missing = [p for p in paths if not p.is_file()]
    for p in missing:
        print(f"! not a file: {p}")
    paths = [p for p in paths if p.is_file()]

    if not paths:
        print("nothing to do")
        sys.exit(1)

    results = {"ok": 0, "have": 0, "none": 0, "failed": 0}
    for p in paths:
        try:
            results[attach(p, args)] += 1
        except Exception as e:
            print(f"   ! failed: {e}")
            results["failed"] += 1

    print(f"\n{results['ok']} done, {results['have']} already had lyrics, "
          f"{results['none']} with no lyrics found, {results['failed']} failed")
    if args.dry_run:
        print("(dry run - nothing was written)")


if __name__ == "__main__":
    main()
