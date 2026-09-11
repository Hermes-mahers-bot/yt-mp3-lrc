#!/usr/bin/env python3
"""
yt2mp3lrc - pull audio from YouTube as MP3, then get the lyrics INTO the MP3.

What it does, per video:
    URL  ->  Music/<Artist> - <Title>.mp3     <- lyrics embedded in the ID3 tag (one file)
    URL  ->  Music/<Artist> - <Title>.lrc     <- synced timing, for players that need it

Why both:
  * The lyrics are written into the MP3 itself (ID3 USLT frame), so the single file carries
    its own lyrics. Players that show embedded lyrics (Musicolet, Poweramp, foobar2000, Kodi)
    read it with no companion file.
  * The timing (the [mm:ss.xx] timestamps) goes in the .lrc sidecar, because that is what
    players actually use for karaoke-style *synced* display. ID3's synced frame (SYLT) exists
    but almost nothing supports it - not even mp3tag can write it.
  So: one file carries the words, the sidecar carries the timing. Both are written by default;
  turn either off with --no-embed / --no-sidecar.

No cover art. Two dependencies: yt-dlp + ffmpeg.

Usage:
    python3 yt2mp3lrc.py "https://youtu.be/XXXXXXXXXXX"
    python3 yt2mp3lrc.py "https://url1" "https://url2"
    python3 yt2mp3lrc.py -f urls.txt                  # one URL per line
    python3 yt2mp3lrc.py "https://www.youtube.com/playlist?list=XXXX"
    python3 yt2mp3lrc.py --force "URL"                # redo even if already done
    python3 yt2mp3lrc.py --no-sidecar "URL"           # embed only, strictly one file
    python3 yt2mp3lrc.py --no-embed "URL"             # .lrc sidecar only

Requires:
    pip install yt-dlp      (ffmpeg must be on PATH)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
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
USER_AGENT = "yt2mp3lrc/1.2 (https://github.com/Hermes-mahers-bot/yt-mp3-lrc)"

# Extra yt-dlp options injected into every request (cookies, when the user passes them).
# YouTube asks "Sign in to confirm you're not a bot" for a lot of connections, especially
# mobile/carrier IPs behind CGNAT and datacenter IPs. Logged-in browser cookies fix it.
YTDL_EXTRA = {}

# Browsers yt-dlp can pull cookies out of.
KNOWN_BROWSERS = {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"}

# yt-dlp now REQUIRES an external JavaScript runtime for YouTube (same status as ffmpeg) -
# without one, downloads fail with "HTTP Error 403: Forbidden". Deno is the only runtime
# yt-dlp enables automatically; the rest have to be asked for explicitly. Ordered by preference.
JS_RUNTIMES = ("deno", "node", "bun", "quickjs")
DENO_INSTALL = "curl -fsSL https://deno.land/install.sh | sh"

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

# Leading timestamps / tags on an LRC line: "[00:10.91] ", "[ar:Artist]", "[ti:Title]".
LRC_PREFIX = re.compile(r"^\s*(\[\d{1,3}:\d{2}(\.\d{1,3})?\]|\[[a-z]{2,3}:[^\]]*\])+\s*", re.IGNORECASE)

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


def strip_lrc_timestamps(lrc_text):
    """LRC -> readable plain text, for embedding in the ID3 tag."""
    lines = []
    for line in lrc_text.splitlines():
        text = LRC_PREFIX.sub("", line).rstrip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def has_embedded_lyrics(mp3_path):
    """True if the file already carries an ID3 USLT (lyrics) frame."""
    try:
        return b"USLT" in mp3_path.read_bytes()
    except OSError:
        return False


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


def _artist_tokens(name):
    """Significant lowercase words in an artist name, ignoring feat./ft./& and punctuation."""
    name = re.sub(r"\b(feat|ft|featuring|with|and|the)\b", " ", (name or ""), flags=re.IGNORECASE)
    name = re.sub(r"[^\w\s]", " ", name.lower())
    return {t for t in name.split() if len(t) > 2}


def artist_matches(want, got):
    """True if the wanted artist and the LRCLIB artist plausibly refer to the same act.

    Guards against the nasty false positive: two unrelated songs with the same title and
    almost the same duration. Examples caught in testing:
      * "Xenogenesis" by 3TEETH (233s) vs a TheFatRat video (235s)
      * "Firefly" by Mura Masa (224s) vs a "Jim Yosef - Firefly" video (227s)
    Both would have written completely unrelated lyrics onto the file.
    """
    if not want or not got:
        return True              # nothing to compare -> allow
    return bool(_artist_tokens(want) & _artist_tokens(got))


def title_matches(want, got):
    """Loose title check, used only for the free-text fallback where nothing else scopes
    the result to the right song. Ignores words of 3 letters or fewer, so short titles like
    "On & On" fall through as "cannot judge" instead of being wrongly rejected."""
    if not want or not got:
        return True
    a = {w for w in re.sub(r"[^\w\s]", " ", want.lower()).split() if len(w) > 3}
    b = {w for w in re.sub(r"[^\w\s]", " ", got.lower()).split() if len(w) > 3}
    if not a or not b:
        return True
    return bool(a & b)


def _pick_candidate(candidates, duration, tol, want_artist, want_track=None):
    """Best candidate: prefer one with synced lyrics, else any with plain lyrics."""
    plain_backup = None
    for cand in candidates or []:
        if not (cand.get("syncedLyrics") or cand.get("plainLyrics")):
            continue
        if not artist_matches(want_artist, cand.get("artistName")):
            continue
        if want_track and not title_matches(want_track, cand.get("trackName")):
            continue
        if not duration_ok(cand, duration, tol):
            continue
        if cand.get("syncedLyrics"):
            return cand
        if plain_backup is None:
            plain_backup = cand
    return plain_backup


def find_lyrics(artist, track, album, duration):
    """Return {'synced': str|None, 'plain': str|None}, or None if LRCLIB has nothing.

    Three passes: exact lookup -> fuzzy search on track name -> free-text search.
    The duration window is what stops a live version / cover / remix matching the wrong track.
    """
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
        if (rec and artist_matches(artist, rec.get("artistName"))
                and duration_ok(rec, duration)
                and (rec.get("syncedLyrics") or rec.get("plainLyrics"))):
            return {"synced": rec.get("syncedLyrics"), "plain": rec.get("plainLyrics")}

    # 2. fuzzy search on the track name alone, strict duration window.
    #    "&" and "and" are both common in titles, and "(feat. ...)" breaks matching.
    variants = [track]
    if "&" in track:
        variants.append(track.replace("&", "and"))
    elif re.search(r"\band\b", track, re.IGNORECASE):
        variants.append(re.sub(r"\band\b", "&", track, flags=re.IGNORECASE))
    variants.append(re.sub(r"\s*[\(\[].*?[\)\]]", "", track).strip())   # drop "(feat. ...)"

    for query in dict.fromkeys(v for v in variants if v):
        qs = urllib.parse.urlencode({"track_name": query})
        cand = _pick_candidate(_get_json(f"{LRCLIB}/search?{qs}"), duration,
                              DURATION_TOLERANCE, artist)
        if cand:
            return {"synced": cand.get("syncedLyrics"), "plain": cand.get("plainLyrics")}

    # 3. last resort: free-text search, looser window
    if artist:
        qs = urllib.parse.urlencode({"q": f"{artist} {track}"})
        cand = _pick_candidate(_get_json(f"{LRCLIB}/search?{qs}"), duration, 5, artist, track)
        if cand:
            return {"synced": cand.get("syncedLyrics"), "plain": cand.get("plainLyrics")}

    return None


# ---------------------------------------------------------------- download + embed


class _Capture:
    """Collects yt-dlp's error lines.

    yt-dlp needs ignoreerrors=True so one dead video doesn't kill a whole playlist, but that
    also swallows real failures (like YouTube's bot check) and leaves us with an empty result
    and no explanation. This keeps the error text so it can be reported properly.
    """

    def __init__(self):
        self.errors = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.errors.append(msg)


def video_urls(url):
    """Expand a playlist/channel URL into individual video URLs."""
    # A plain single-video URL needs no probe request - go straight at it. Fewer requests to
    # YouTube means fewer chances of tripping its bot check.
    if "list=" not in url and not re.search(r"/(playlist|channel|c/|user/|@)", url):
        return [url]

    from yt_dlp import YoutubeDL

    cap = _Capture()
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
            "skip_download": True, "ignoreerrors": True, "logger": cap, **YTDL_EXTRA}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise RuntimeError(cap.errors[-1] if cap.errors else "could not read that URL")
    if info.get("_type") == "playlist":
        found = [e.get("url") or e.get("webpage_url") for e in (info.get("entries") or []) if e]
        if not found:
            raise RuntimeError(cap.errors[-1] if cap.errors else "playlist has nothing playable")
        return found
    return [info.get("webpage_url") or url]


def fetch_metadata(vurl):
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, **YTDL_EXTRA}
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
        **YTDL_EXTRA,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(vurl, download=True)

    # Ask yt-dlp where the file landed; fall back to globbing the stem.
    for d in info.get("requested_downloads") or []:
        p = Path(d.get("filepath", ""))
        if p.suffix.lower() == ".mp3" and p.exists():
            return p
    for p in sorted(OUT_DIR.glob(f"{stem}.*")):
        if p.suffix.lower() == ".mp3":
            return p
    raise RuntimeError(f"download finished but no .mp3 found for stem {stem!r}")


def embed_lyrics(mp3_path, lyrics_text):
    """Write lyrics into the MP3's ID3 USLT frame.

    The audio stream is copied (-c copy), never re-encoded, so the sound is bit-identical.
    ffmpeg cannot edit in place: write a temp file, then swap it in.
    """
    tmp = mp3_path.with_name(mp3_path.name + ".embedding.mp3")
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(mp3_path),
        "-c", "copy",
        "-id3v2_version", "3",          # ID3v2.3: the widest player support for USLT
        "-metadata", f"lyrics={lyrics_text}",
        str(tmp),
    ]
    subprocess.run(cmd, check=True)
    os.replace(tmp, mp3_path)


# ---------------------------------------------------------------- per-video flow


def process(vurl, force, embed, sidecar):
    info = fetch_metadata(vurl)
    artist, track, album = split_artist_track(info)
    duration = info.get("duration")
    stem = pick_output_stem(artist, track, info.get("id", "track"))
    mp3 = OUT_DIR / f"{stem}.mp3"
    lrc = OUT_DIR / f"{stem}.lrc"

    log(f"-> {info.get('title', vurl)}")
    log(f"   {artist or '?'} / {track or '?'}  ({duration or '?'}s)")

    if mp3.exists() and not force:
        log("   = mp3 already present")
    else:
        mp3 = download_mp3(vurl, stem)
        log(f"   + {mp3.name}")

    # What is still missing? (so an old file picky about one of them gets upgraded, not skipped)
    need_sidecar = sidecar and (force or not lrc.exists())
    need_embed = embed and (force or not has_embedded_lyrics(mp3))
    if not (need_sidecar or need_embed):
        log("   = lyrics already present, skipping (use --force to redo)")
        return

    found = find_lyrics(artist, track, album, duration)
    if not found:
        log("   - no lyrics found (instrumental, or not in LRCLIB)")
        return

    synced, plain = found["synced"], found["plain"]
    if need_sidecar and synced:
        # .lrc must sit next to the audio with the same basename for players to auto-load.
        lrc.write_text(synced, encoding="utf-8")
        log(f"   + {lrc.name}  (synced, {len(synced.splitlines())} lines)")

    if need_embed:
        # Embed readable text: LRCLIB's plain lyrics, else the synced text with timestamps stripped.
        text = plain or strip_lrc_timestamps(synced or "")
        if text:
            embed_lyrics(mp3, text)
            log(f"   + lyrics embedded in {mp3.name}  ({len(text.splitlines())} lines)")
        else:
            log("   - nothing embeddable")


def find_js_runtimes():
    """Return {name: path} for the JS runtimes present on PATH."""
    return {name: p for name in JS_RUNTIMES if (p := shutil.which(name))}


def setup_js_runtime(explicit):
    """Make sure yt-dlp has a JavaScript runtime, or say why downloads will fail.

    Deno is auto-detected by yt-dlp, so if it's installed there is nothing to do. If only
    node/bun/quickjs is available we have to enable it explicitly. If nothing is available,
    every download will fail with HTTP 403 - say that up front instead of letting the user
    guess.
    """
    if explicit:
        YTDL_EXTRA["js_runtimes"] = explicit
        log(f"   js runtime: {', '.join(sorted(explicit))}")
        return

    found = find_js_runtimes()
    if "deno" in found:
        return                                    # yt-dlp picks deno up by itself

    if found:
        name = next(n for n in JS_RUNTIMES if n in found)     # best available
        YTDL_EXTRA["js_runtimes"] = {name: {}}
        log(f"! deno not found - using {name} ({found[name]}) as the JavaScript runtime.")
        log(f"  (deno is the only one yt-dlp auto-detects; install it to drop this flag.)\n")
        return

    log("! No JavaScript runtime found (deno, node, bun or quickjs).")
    log("  YouTube downloads now REQUIRE one - without it you get HTTP 403 Forbidden.")
    log(f"  Install deno, then retry:   {DENO_INSTALL}")
    log("  (or install Node.js and pass --js-runtime node)\n")


def explain(err):
    """Turn yt-dlp's common failures into something actionable."""
    msg = str(err)
    low = msg.lower()
    if "no module named 'yt_dlp'" in low or "no module named yt_dlp" in low:
        return ("yt-dlp isn't installed for the python you're running. Fix with: "
                "python3 -m pip install -U yt-dlp   (use the same python you run this with)")
    if "not a bot" in low or "sign in" in low:
        if YTDL_EXTRA.get("cookiesfrombrowser") or YTDL_EXTRA.get("cookiefile"):
            return ("YouTube still refuses even with the cookies you passed. Usually the browser "
                    "isn't logged in, you picked the wrong profile, or the cookie file is stale. "
                    "Try BROWSER:PROFILE, or export a fresh cookies.txt and pass --cookies, or "
                    "try --player-client web_safari")
        return ("YouTube is blocking this connection (bot check). Carrier/mobile IPs and "
                "datacenter IPs get this. Fix: python3 yt2mp3lrc.py "
                "--cookies-from-browser firefox \"URL\"")
    if "403" in low or "forbidden" in low:
        return ("YouTube refused the download (403). In order of likelihood: (1) yt-dlp is "
                "outdated - run: python3 -m pip install -U yt-dlp   (2) no JavaScript runtime - "
                f"install deno: {DENO_INSTALL}   (3) try --player-client tv")
    if "ffmpeg" in low and ("not found" in low or "no such file" in low):
        return "ffmpeg isn't on PATH for this shell. Install it, then reopen the terminal."
    if "could not find" in low and "cookies database" in low:
        return ("no cookies database found for that browser. Is it installed and logged in? "
                "Use BROWSER:PROFILE to pick a profile, or export a cookies.txt instead.")
    if "unsupported browser" in low:
        return "that browser isn't supported by yt-dlp. Try firefox, chrome, brave, edge, chromium."
    if "private video" in low or "video unavailable" in low or "removed" in low:
        return "that video is unavailable, private or deleted"
    if "unsupported url" in low:
        return "that doesn't look like a URL yt-dlp supports"
    return msg.splitlines()[0][:200] if msg else "unknown error"


def main():
    global OUT_DIR

    ap = argparse.ArgumentParser(description="Download YouTube audio as MP3 and put the lyrics inside it.")
    ap.add_argument("urls", nargs="*", help="video or playlist URLs")
    ap.add_argument("-f", "--file", help="text file with one URL per line")
    ap.add_argument("--force", action="store_true", help="re-download and re-fetch lyrics")
    ap.add_argument("-o", "--out", help="output folder (default: Music, next to where you run this)")
    ap.add_argument("--no-embed", action="store_true", help="don't write lyrics into the MP3 tag")
    ap.add_argument("--no-sidecar", action="store_true", help="don't write the .lrc sidecar")
    ap.add_argument("--cookies-from-browser", metavar="BROWSER",
                    help="read cookies from a browser you're logged into (firefox, chrome, brave, "
                         "edge, chromium, opera, vivaldi). Use BROWSER:PROFILE to pick a profile.")
    ap.add_argument("--cookies", metavar="FILE",
                    help="read cookies from a Netscape-format cookies.txt file instead")
    ap.add_argument("--player-client", metavar="NAME",
                    help="ask YouTube for a different player client (e.g. web_safari, mweb, tv). "
                         "Worth trying when the bot check blocks you and cookies are awkward.")
    ap.add_argument("--js-runtime", metavar="NAME[:PATH]", action="append",
                    help="enable a JavaScript runtime for YouTube (deno is auto-detected; use this "
                         "for node, bun or quickjs, or a deno outside PATH). Repeatable.")
    args = ap.parse_args()

    if args.cookies_from_browser:
        name = args.cookies_from_browser.split(":", 1)[0].lower()
        if name not in KNOWN_BROWSERS:
            ap.error(f"unknown browser {name!r}. Pick one of: {', '.join(sorted(KNOWN_BROWSERS))}")
        YTDL_EXTRA["cookiesfrombrowser"] = tuple(args.cookies_from_browser.split(":", 1))
    if args.cookies:
        if not Path(args.cookies).is_file():
            ap.error(f"cookie file not found: {args.cookies}")
        YTDL_EXTRA["cookiefile"] = args.cookies
    if args.player_client:
        YTDL_EXTRA["extractor_args"] = {"youtube": {"player_client": [args.player_client]}}

    explicit_js = {}
    for spec in args.js_runtime or []:
        name, _, path = spec.partition(":")
        name = name.lower()
        if name not in JS_RUNTIMES:
            ap.error(f"unknown JS runtime {name!r}. Pick one of: {', '.join(JS_RUNTIMES)}")
        explicit_js[name] = {"path": path} if path else {}
    setup_js_runtime(explicit_js)

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

    log(f"saving to {OUT_DIR.resolve()}/\n")
    total = 0
    for url in urls:
        try:
            vurls = video_urls(url)
        except Exception as e:
            log(f"! {url}\n   ! {explain(e)}")
            continue
        if not vurls:
            log(f"! {url}\n   ! nothing found there")
            continue
        for vurl in vurls:
            total += 1
            try:
                process(vurl, args.force, not args.no_embed, not args.no_sidecar)
            except Exception as e:
                log(f"   ! failed: {explain(e)}")
    log(f"\ndone. {total} item(s) processed into {OUT_DIR}/")


if __name__ == "__main__":
    main()
