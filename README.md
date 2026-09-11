# yt-mp3-lrc

Download audio from YouTube as **MP3** and fetch **synced lyrics** as a `.lrc` sidecar that music players actually read.

```
URL  ->  Music/Alan Walker - Faded.mp3
URL  ->  Music/Alan Walker - Faded.lrc     (only when synced lyrics are found)
```

No cover art. No config file. No database. No embedded tags beyond what yt-dlp adds.

## Install

```bash
pip install yt-dlp        # ffmpeg must also be on PATH
```

## Usage

```bash
python3 yt2mp3lrc.py "https://youtu.be/XXXXXXXXXXX"          # one video
python3 yt2mp3lrc.py "https://url1" "https://url2"           # several
python3 yt2mp3lrc.py -f urls.txt                             # one URL per line
python3 yt2mp3lrc.py "https://www.youtube.com/playlist?list=XXXX"   # whole playlist
python3 yt2mp3lrc.py --force "URL"                           # redo even if files exist
python3 yt2mp3lrc.py -o /media/sdcard/Music "URL"            # custom output folder
```

Re-running is safe: if the `.mp3` and `.lrc` already exist, the track is skipped. After adding
new tracks, just run it again — nothing is re-downloaded.

## How the lyrics matching works

Lyrics come from [LRCLIB](https://lrclib.net) (free, open, no account, no API key).

YouTube titles are messy, so the tool does three passes, in order:

1. **Exact lookup** — `artist + track + album + duration` against `/api/get`.
2. **Fuzzy search on track name** — tries the title as-is, then with `&`↔`and` swapped, then with
   `(feat. ...)` removed. Candidates must have synced lyrics **and** a duration within **±3 s** of
   the video.
3. **Free-text search** — `"artist track"` query, duration window relaxed to **±5 s**.

The duration window is the important part. Without it you regularly get the lyrics of a live
version, a cover, or an extended remix pasted onto the wrong recording.

Title junk is stripped first: `(Official Music Video)`, `[NCS Release]`, `[4K UPGRADE]`,
`(Lyrics)`, `| Label | Genre` tails, and so on. Label channels (`NoCopyrightSounds`,
`Monstercat`, `Proximity`, ...) are not treated as the artist.

## Expected hit rate

| Track type | Result |
|---|---|
| Mainstream vocals (Alan Walker, Avicii, Linkin Park) | hit |
| Popular NCS / EDM tracks with vocals | hit |
| Instrumentals (most NCS drops, TheFatRat instrumentals) | **no `.lrc` — this is correct** |
| Obscure remixes, extended edits, unofficial uploads | frequently miss |

A miss is not an error. The MP3 is still downloaded; the track just has no lyrics file.

## Notes

- **MP3 quality** defaults to lame **V0** (`MP3_QUALITY = "0"`, ~245 kbps VBR). YouTube's source is
  ~160 kbps Opus, so encoding to 320 kbps CBR adds no information — only size. Change the constant
  to `"320"` or `"192"` if you prefer CBR.
- **Sidecar naming**: the standard is `Song.lrc` next to `Song.mp3`, which is what Poweramp,
  Musicolet, foobar2000, MusicBee, VLC, mpv and most DAPs expect. A few players look for
  `Song.mp3.lrc` instead — if one doesn't pick it up, just copy the file under that name too.
- **No cover art**, per spec. Add `--embed-thumbnail` to yt-dlp's postprocessor section if you
  ever want it.
- **Lyrics work offline** on the player. Budget DAPs don't fetch anything themselves, which is
  exactly why the `.lrc` sits in the folder next to the audio.

## Known limitations

- **YouTube blocks datacenter IPs.** Running this on a VPS fails with
  *"Sign in to confirm you're not a bot."* Run it from your home connection, or pass cookies to
  yt-dlp (`--cookies-from-browser firefox` / `--cookies cookies.txt`). This is a YouTube-side
  restriction, not a bug in this tool.
- Newer yt-dlp versions also want a JavaScript runtime (deno) for full YouTube extraction.
- LRCLIB is crowd-sourced, so coverage is good but not complete.

## Files

| File | Purpose |
|---|---|
| `yt2mp3lrc.py` | the whole tool |
| `test_match.py` | checks YouTube title → artist/track → LRCLIB matching against the live API |
| `requirements.txt` | `yt-dlp` |

## Verification status

Verified working (2026-09, Linux, ffmpeg 6.1.1, yt-dlp 2026.08.19):

- Real download → real MP3 conversion, via yt-dlp + ffmpeg.
- `.lrc` sidecar written with matching basename, correct timed lines, UTF-8.
- Title cleaning and LRCLIB matching against 9 real YouTube titles: **7/7 vocal tracks matched**
  (Faded, On & On, Sing Me To Sleep, Firefly, Wake Me Up, Numb), **2/2 instrumentals correctly
  missed**.
- Re-run skips existing files; instrumentals don't crash or write an empty `.lrc`.

**Not verified:** the YouTube extraction step itself, because YouTube refuses datacenter IPs
("Sign in to confirm you're not a bot") regardless of player client. Run `test_match.py` and a
single URL from your own machine to confirm that last hop.
