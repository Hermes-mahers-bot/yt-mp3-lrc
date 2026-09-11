#!/usr/bin/env python3
"""
yt2mp3lrc - pull audio from YouTube as MP3, then fetch synced lyrics (.lrc sidecar).

What it does, per video:
    URL  ->  Music/<Artist> - <Title>.mp3
    URL  ->  Music/<Artist> - <Title>.lrc     (only when synced lyrics are found)

No cover art, no external database, no config file. Two dependencies: yt-dlp + ffmpeg.

Usage:
    python3 yt2mp3lrc.py "https://youtu.be/XXXXXXXXXXX"
    python3 yt2mp3lrc.py "https://url1" "https://url2"
    python3 yt2mp3lrc.py -f urls.txt              # one URL per line
    python3 yt2mp3lrc.py "https://www.youtube.com/playlist?list=XXXX"
    python3 yt2mp3lrc.py --force "URL"            # re-download even if files exist

Requires:
    pip install yt-dlp      (ffmpeg must be on PATH)
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- settings

OUT_DIR = Path("Music")          # where mp3 + lrc files go
MP3_QUALITY = "0"                # lame V0 (~245 kbps VBR). "320" for CBR 320, "192" for CBR 192.
DURATION_TOLERANCE = 3           # seconds. LRCLIB candidates must match the video length this closely.
LRCLIB = "https://lrclib.net/api"
USER_AGENT = "yt2mp3lrc/1.0 (https://github.com/Hermes-mahers-bot/yt-mp3-lrc)"

# YouTube channels/uploaders that are labels, not artists. If the "artist" is one of
# these, we drop it and match on the track name alone.
LABELS = {
    "nocopyrightsounds", "ncs", "monstercat", "proximity", "trap nation",
    "mrsuicidesheep", "spinnin' records", "ultra music", "xkito music",
    "liquicity", "cloudkid", "tasty", "network 1", "airwave music tv",
}

# Bracketed junk that appears in YouTube titles, e.g. "(Official Music Video)", "[4K UPGRADE]",
# "[NCS Release]". Any bracket containing one of these words is dropped.
TITLE_JUNK = re.compile(
    r"[\(\[]\s*[^\)\]]*?\b("
    r"official|video|audio|lyric|lyrics|visuali[sz]er|hd|hq|[48]k|mv|m/v|"
    r"ncs release|monstercat release|free download|out now|premiere|"
    r"clip officiel|upgrade|remaster(ed)?|lyric video"
    r")\b[^\)\]]*?[\)\]]",
    re.IGNORECASE,
)

# ---------------------------------------------------------------- small helpers


def log(msg):
    print(msg, flush=True)


def safe_filename(name):
    """Strip characters that break filesystems."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:150] or "untitled"


def clean_track_name(title):
    """Turn a messy YouTube title into something LRCLIB can match."""
    t = TITLE_JUNK.sub(" ", title)
    t = t.split("|")[0]                      # "Artist - Song | Label | Genre" -> "Artist - Song"
    t = re.sub(r"\s*[-–]\s*topic\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip(" -–—")
    return t


def split_artist_track(info):
    """Best-effort artist/track/album from a yt-dlp info dict."""
    artist = (info.get("artist") or info.get("creator") or info.get("uploader") or "").strip()
    track = (info.get("track") or "").strip()
    album = (info.get("album") or "").strip()

    if not track:
        title = clean_track_name(info.get("title") or "")
        # Only trust "Artist - Track" if the left side is short (a real artist name).
        if " - " in title and len(title.split(" - ")[0]) <= 40:
            left, right = title.split(" - ", 1)
            track = right.strip()
            if not artist or artist.lower() in LABELS:
                artist = left.strip()
        else:
            track = title

    if artist.lower() in LABELS:
        artist = ""
    return artist, track, album


def pick_output_stem(artist, track, fallback):
    if artist:
        return safe_filename(f"{artist} - {track}")
    return safe_filename(track or fallback)


# ---------------------------------------------------------------- LRCLIB


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None          # LRCLIB's "no exact match" answer
        log(f"   ! LRCLIB HTTP {e.code}")
        return None
    except Exception as e:
        log(f"   ! LRCLIB error: {e}")
        return None


def duration_ok(candidate, duration, tol=DURATION_TOLERANCE):
    cd = candidate.get("duration")
    if not duration or not cd:
        return True              # nothing to compare against -> allow
    return abs(float(cd) - float(duration)) <= tol


def find_synced_lyrics(artist, track, album, duration):
    """Return synced lyrics text, or None. Exact match first, then fuzzy search."""
    if not track:
        return None

    # 1. exact match (artist + track + duration)
    if artist:
        params = {"artist_name": artist, "track_name": track}
        if album:
            params["album_name"] = album
        if duration:
            params["duration"] = int(duration)
        rec = _get_json(f"{LRCLIB}/get?{urllib.parse.urlencode(params)}")
        if rec and rec.get("syncedLyrics"):
            return rec["syncedLyrics"]

    # 2. fuzzy search on the track name alone, strict duration window
    variants = [track]
    if "&" in track:
        variants.append(track.replace("&", "and"))
    elif re.search(r"\band\b", track, re.IGNORECASE):
        variants.append(re.sub(r"\band\b", "&", track, flags=re.IGNORECASE))
    variants.append(re.sub(r"\s*[\(\[].*?[\)\]]", "", track).strip())   # drop "(feat. ...)"

    for query in dict.fromkeys(v for v in variants if v):
        for cand in _get_json(f"{LRCLIB}/search?{urllib.parse.urlencode({'track_name': query})}") or []:
            if cand.get("syncedLyrics") and duration_ok(cand, duration):
                return cand["syncedLyrics"]

    # 3. last resort: free-text search, looser window
    if artist:
        q = urllib.parse.urlencode({"q": f"{artist} {track}"})
        for cand in _get_json(f"{LRCLIB}/search?{q}") or []:
            if cand.get("syncedLyrics") and duration_ok(cand, duration, tol=5):
                return cand["syncedLyrics"]

    return None


# ---------------------------------------------------------------- download


def video_urls(url):
    """Expand a playlist/channel URL into individual video URLs."""
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
            "skip_download": True, "ignoreerrors": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return []
    if info.get("_type") == "playlist":
        return [e.get("url") or e.get("webpage_url") for e in (info.get("entries") or []) if e]
    return [info.get("webpage_url") or url]


def fetch_metadata(vurl):
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(vurl, download=False)


def download_mp3(vurl, stem):
    """Download and convert to MP3. Returns the path of the finished .mp3."""
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": {"default": str(OUT_DIR / f"{stem}.%(ext)s")},
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": MP3_QUALITY,
        }],
        "overwrites": True,
        "noprogress": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(vurl, download=True)

    # Ask yt-dlp where the file landed; fall back to globbing the stem.
    for d in info.get("requested_downloads") or []:
        p = Path(d.get("filepath", ""))
        if p.suffix.lower() == ".mp3" and p.exists():
            return p
    hits = sorted(OUT_DIR.glob(f"{stem}.*"))
    for p in hits:
        if p.suffix.lower() == ".mp3":
            return p
    raise RuntimeError(f"download finished but no .mp3 found for stem {stem!r}")


# ---------------------------------------------------------------- per-video flow


def process(vurl, force):
    info = fetch_metadata(vurl)
    artist, track, album = split_artist_track(info)
    duration = info.get("duration")
    stem = pick_output_stem(artist, track, info.get("id", "track"))
    mp3 = OUT_DIR / f"{stem}.mp3"
    lrc = OUT_DIR / f"{stem}.lrc"

    log(f"-> {info.get('title', vurl)}")
    log(f"   {artist or '?'} / {track or '?'}  ({duration or '?'}s)")

    if mp3.exists() and lrc.exists() and not force:
        log("   = already downloaded + lyrics present, skipping (use --force to redo)")
        return

    if mp3.exists() and not force:
        log("   = mp3 already present")
    else:
        mp3 = download_mp3(vurl, stem)
        log(f"   + {mp3.name}")

    if lrc.exists() and not force:
        log("   = lyrics already present")
        return

    lyrics = find_synced_lyrics(artist, track, album, duration)
    if lyrics:
        # .lrc must sit next to the audio with the same basename for players to auto-load.
        lrc.write_text(lyrics, encoding="utf-8")
        log(f"   + {lrc.name}  ({len(lyrics.splitlines())} timed lines)")
    else:
        log("   - no synced lyrics found (instrumental, or not in LRCLIB)")


def main():
    global OUT_DIR

    ap = argparse.ArgumentParser(description="Download YouTube audio as MP3 + synced .lrc lyrics.")
    ap.add_argument("urls", nargs="*", help="video or playlist URLs")
    ap.add_argument("-f", "--file", help="text file with one URL per line")
    ap.add_argument("--force", action="store_true", help="re-download and re-fetch lyrics")
    ap.add_argument("-o", "--out", help="output folder (default: Music)")
    args = ap.parse_args()

    if args.out:
        OUT_DIR = Path(args.out)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    urls = list(args.urls)
    if args.file:
        urls += [ln.strip() for ln in Path(args.file).read_text().splitlines()
                 if ln.strip() and not ln.startswith("#")]
    if not urls:
        ap.print_help()
        sys.exit(1)

    total = 0
    for url in urls:
        for vurl in video_urls(url):
            total += 1
            try:
                process(vurl, args.force)
            except Exception as e:
                log(f"   ! failed: {e}")
    log(f"\ndone. {total} item(s) processed into {OUT_DIR}/")


if __name__ == "__main__":
    main()
