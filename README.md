# yt-mp3-lrc

Download audio from YouTube as **MP3**, with the **lyrics inside the MP3 file** and the synced timing alongside it.

```
URL  ->  Music/Alan Walker - Faded.mp3     lyrics embedded in the file's ID3 tag
URL  ->  Music/Alan Walker - Faded.lrc     [mm:ss.xx] timing, for players that want it
```

No cover art. No config file. No database. One dependency: `yt-dlp` (+ `ffmpeg` on PATH).

## Why both the tag and the sidecar

| | What it holds | Who reads it |
|---|---|---|
| **ID3 tag in the MP3** | the words, as readable plain text | Musicolet, Poweramp, foobar2000, Kodi, iTunes-style players — no companion file needed |
| **`.lrc` sidecar** | the same lyrics *with* `[mm:ss.xx]` timestamps | players that scroll lyrics in time with the song (Musicolet, Poweramp, VLC, mpv, budget DAPs) |

The timing has to live in the sidecar, because ID3's own synchronized frame (`SYLT`) is so badly
supported that even mp3tag cannot write it. So the MP3 carries the words, the sidecar carries the
timing. Both are written by default; `--no-embed` or `--no-sidecar` turns either off.

If you want **strictly one file per song**, use `--no-sidecar`: the lyrics still travel inside the MP3.

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
python3 yt2mp3lrc.py --force "URL"                           # redo even if already done
python3 yt2mp3lrc.py -o /media/sdcard/Music "URL"            # custom output folder
python3 yt2mp3lrc.py --no-sidecar "URL"                      # embed only: one file per song
python3 yt2mp3lrc.py --no-embed "URL"                        # .lrc sidecar only
```

Re-running is safe and cheap: whatever is already done gets skipped, so you can point it at the same
folder every time you add music.

## How the lyric matching works

Lyrics come from [LRCLIB](https://lrclib.net) (free, open, no account, no API key). Three passes:

1. **Exact lookup** — `artist + track + album + duration` against `/api/get`.
2. **Fuzzy search on track name** — the title as-is, then `&`↔`and` swapped, then with
   `(feat. ...)` removed.
3. **Free-text search** — `"artist track"`, duration window relaxed to ±5 s.

Every candidate must pass **all** of these guards:

- **Duration window** — ±3 s (±5 s on the last pass) against the video length. This is what stops
  a live version or an extended edit matching the wrong recording.
- **Artist guard** — the LRCLIB artist must share a significant word with the expected artist.
- **Title guard** — on the free-text pass only, the candidate's title must share a word.

The artist guard exists because of a real bug found during testing, not theory. LRCLIB contains
unrelated songs that share a title *and* a near-identical duration:

| Video | Wrong match it used to take | Result |
|---|---|---|
| TheFatRat – Xenogenesis (235 s) | 3TEETH – Xenogenesis (233 s) | metal lyrics on an EDM instrumental |
| Jim Yosef – Firefly (227 s) | Mura Masa feat. NAO – Firefly (224 s) | R&B lyrics on a drum & bass track |

Title junk is stripped before matching (`(Official Music Video)`, `[NCS Release]`, `[4K UPGRADE]`,
`(Lyrics)`, `| Label | Genre` tails), and label channels (`NoCopyrightSounds`, `Monstercat`,
`Proximity`, ...) are never treated as the artist.

## What gets embedded

The ID3 `USLT` frame is written with **readable text** — LRCLIB's plain lyrics, or the synced lyrics
with the `[mm:ss.xx]` prefixes stripped out. Timestamps are deliberately *not* embedded: a player
that only displays embedded lyrics as plain text would otherwise show you bracket noise. The timing
stays in the `.lrc`.

The audio stream is written with `-c copy`, so **the sound is bit-identical** before and after
embedding — verified by comparing the MD5 of the decoded PCM. Existing title/artist/album tags are
preserved.

## Expected hit rate

| Track type | Result |
|---|---|
| Mainstream vocals (Alan Walker, Avicii, Linkin Park) | hit |
| Popular NCS / EDM tracks with vocals | hit |
| Instrumentals, and tracks LRCLIB has no lyrics for | **no lyrics — correct, not an error** |
| Obscure remixes, extended edits, unofficial uploads | frequently miss |

A miss is not a failure: the MP3 is still downloaded, it just has no lyrics. Nothing bogus is written.

## Notes

- **MP3 quality** defaults to lame **V0** (`MP3_QUALITY = "0"`, ~245 kbps VBR). YouTube's source is
  ~160 kbps Opus, so CBR 320 adds no information — only size. Change the constant to `"320"` or
  `"192"` for CBR.
- **Sidecar naming**: standard is `Song.lrc` beside `Song.mp3`, which is what Poweramp, Musicolet,
  foobar2000, MusicBee, VLC, mpv and most DAPs expect. A few players look for `Song.mp3.lrc` — if
  one doesn't pick it up, copy the file under that name too.
- **No cover art**, per spec.
- Lyrics are **offline** once downloaded. Budget DAPs don't fetch anything themselves, which is the
  whole reason the `.lrc` sits in the folder.

## Known limitations

- **YouTube blocks datacenter IPs.** On a VPS this fails with *"Sign in to confirm you're not a
  bot."* Run it from a home connection, or pass cookies to yt-dlp
  (`--cookies-from-browser firefox` / `--cookies cookies.txt`). YouTube-side restriction, not a bug.
- Newer yt-dlp versions want a JavaScript runtime (deno) for full YouTube extraction.
- LRCLIB is crowd-sourced: coverage is good, not complete.

## Files

| File | Purpose |
|---|---|
| `yt2mp3lrc.py` | the whole tool |
| `test_match.py` | artist/title guards (offline) + title→lyrics matching against the live LRCLIB API |
| `requirements.txt` | `yt-dlp` |

## Verification status

`python3 test_match.py` → **ALL TESTS PASSED** (2026-09, Linux, ffmpeg 6.1.1, yt-dlp 2026.08.19).

Verified:

- **Lyrics really are in the MP3.** `USLT` frame present; the words read back out of the file;
  title/artist/album tags preserved; decoded-audio MD5 unchanged before/after embedding.
- **Timestamps don't leak into the tag** (`[00:` never appears in the embedded text).
- **Live LRCLIB matching, 9 real YouTube titles:** 6 vocal tracks correctly matched with the right
  song's lyrics; 3 correctly returned *nothing* (2 instrumentals + one track LRCLIB has no lyrics
  for).
- **Two false positives found and fixed** via the artist guard, both now regression-tested.
- **Pipeline mechanics:** yt-dlp download → ffmpeg MP3 → `.lrc` sidecar written with matching
  basename, correct timed lines, UTF-8; re-runs skip cleanly; instrumentals neither crash nor write
  an empty `.lrc`; `--no-sidecar` leaves exactly one file.

**Not verified:** the YouTube extraction step itself — YouTube refuses datacenter IPs ("Sign in to
confirm you're not a bot") regardless of player client (`web_safari`, `tv`, `android_vr`, `ios` all
tested). That last hop needs a home connection.
