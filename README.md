# yt-mp3-lrc

Two tools for getting synced lyrics into local music files. Both write the lyrics **into the file's
own tag** and drop a **`.lrc` sidecar** beside it for timed display.

| | What it does | Needs YouTube to work? |
|---|---|---|
| **`addlyrics.py`** | attach lyrics to MP3s you **already have** | **No** — you supply the audio, it only talks to LRCLIB |
| **`yt2mp3lrc.py`** | download from YouTube *and* attach lyrics | Yes (see the troubleshooting section) |

```
song.mp3  ->  lyrics inside song.mp3  +  song.lrc
```

No cover art. No config file. No database.

**Recommended path: `addlyrics.py`.** Grab the audio with whatever tool you like, then point this at
it. It never touches YouTube, so none of the bot-check / 403 / JS-runtime problems below apply.

---

## addlyrics.py — attach lyrics to MP3s you already have

```bash
python3 addlyrics.py song.mp3 --link "https://youtu.be/XXXXXXXXXXX"
python3 addlyrics.py song.mp3                       # works from the file's own tags
python3 addlyrics.py song.mp3 --artist "X" --title "Y"
python3 addlyrics.py *.mp3                          # batch
python3 addlyrics.py /path/to/folder                # whole folder
python3 addlyrics.py song.mp3 --dry-run             # show the match, change nothing
python3 addlyrics.py song.mp3 --no-sidecar          # embed only: one file, no .lrc
python3 addlyrics.py song.mp3 --force               # redo something already done
```

**Requires ffmpeg only.** `yt-dlp` is used *solely* if you pass `--link`, and it is never fatal if
it's missing or fails — the file's own tags are used instead.

### Where it gets the artist/title, in order

1. `--artist` / `--title` / `--album` if you passed them
2. the `--link`'s metadata (needs yt-dlp)
3. the file's own tags — unless the artist tag looks like a channel name (`ANN MUSIC`, `7CLOUDS`,
   `X - Topic`), which is dropped rather than trusted
4. the filename, if it's genuinely `Artist - Title.mp3`
5. **title-only — only if nothing above gave an artist**, and only with a tighter duration window

### The safety rule that matters

Matching needs an **artist** wherever one exists, because same-title-same-duration collisions are
real. LRCLIB genuinely contains, for example:

| Your track | Colliding record | Same title? | Same duration? |
|---|---|---|---|
| TheFatRat – Xenogenesis | 3TEETH – Xenogenesis | yes | 233s vs 235s |
| Jim Yosef – Firefly | Mura Masa feat. NAO – Firefly | yes | 227s vs 224s |

Without the artist, both pass every other check. So a guess that has an artist is always tried
first, and title-only is a last resort that is **loudly flagged in the output**. Wrong lyrics are
worse than no lyrics — a miss tells you why and how to fix it (pass `--artist`/`--title`).

### Reading the output

```
-> Let Me Down Slowly.mp3
   169s | tags: ANN MUSIC / Let Me Down Slowly
   match: Alec Benjamin - Let Me Down Slowly (169s)
   ! MATCHED ON THE TITLE ALONE - verify this is really the right song
   + Let Me Down Slowly.lrc  (synced, 50 lines)
   + lyrics embedded into Let Me Down Slowly.mp3  (49 lines)
```

`match:` always names the exact LRCLIB record used, so a wrong match is visible instead of silent.
**Run `--dry-run` over a batch first** — it prints what would be matched and writes nothing.

The audio is copied with `-c copy`, so **the sound is bit-identical** — verified by comparing the MD5
of the decoded PCM before and after. The result is checked for a readable lyrics tag *before* the
original file is replaced. If ffmpeg fails, your file is untouched.

---

## yt2mp3lrc.py — download from YouTube *and* attach lyrics

Only use this if you want the download handled too. Everything in this section is about YouTube
fighting automated downloads; none of it applies to `addlyrics.py`.

### The two things that break YouTube downloads

#### 1. A JavaScript runtime is now REQUIRED (same status as ffmpeg)

yt-dlp can no longer talk to YouTube without an external JavaScript runtime. Without one, the
download fails with:

```
ERROR: unable to download video data: HTTP Error 403: Forbidden
```

**Deno is the only runtime yt-dlp detects by itself.** Install it:

```bash
curl -fsSL https://deno.land/install.sh | sh
# then make sure it's on PATH (the installer tells you the line to add):
export PATH="$HOME/.deno/bin:$PATH"
deno --version
```

Already have **Node.js v20+**? You don't need deno — just ask for it explicitly:

```bash
python3 yt2mp3lrc.py --js-runtime node "URL"
```

The tool checks for a runtime at startup and tells you what it found (or that nothing is there), so
you'll see this before any download is attempted.

#### 2. YouTube also blocks connections ("Sign in to confirm you're not a bot")

That one is about your **IP**, not your command. It hits mobile/carrier IPs behind CGNAT (you share
one public IP with thousands of people) and datacenter/VPS IPs. Fix it with cookies from a browser
you're logged into:

```bash
python3 yt2mp3lrc.py --cookies-from-browser firefox "URL"
python3 yt2mp3lrc.py --cookies-from-browser chrome  "URL"
python3 yt2mp3lrc.py --cookies-from-browser "firefox:default-release" "URL"   # pick a profile
```

If browser cookies don't work (common with snap/flatpak Firefox, or a locked keyring), export
`cookies.txt` with a "Get cookies.txt LOCALLY" extension and use `--cookies ~/cookies.txt`.

**Also always keep yt-dlp current** — YouTube changes constantly and an outdated yt-dlp produces
403s and extraction failures:

```bash
python3 -m pip install -U yt-dlp
```

Last resort for weird IPs: `--player-client web_safari` (also `mweb`, `tv`, `ios`, `android_vr`).

---

## Why both the tag and the sidecar

| | What it holds | Who reads it |
|---|---|---|
| **ID3 tag in the MP3** | the words, as readable plain text | Musicolet, Poweramp, foobar2000, Kodi, iTunes-style players — no companion file needed |
| **`.lrc` sidecar** | the same lyrics *with* `[mm:ss.xx]` timestamps | players that scroll lyrics in time with the song (Musicolet, Poweramp, VLC, mpv, budget DAPs) |

The timing has to live in the sidecar, because ID3's own synchronized frame (`SYLT`) is so badly
supported that even mp3tag cannot write it. So the MP3 carries the words, the sidecar carries the
timing. Both are written by default; `--no-embed` or `--no-sidecar` turns either off. Use
`--no-sidecar` if you want **strictly one file per song**.

## Install

```bash
python3 -m pip install -U yt-dlp     # keep this current; stale versions break
# and: ffmpeg on PATH, plus deno (or --js-runtime node)
```

## Usage

```bash
python3 yt2mp3lrc.py "https://youtu.be/XXXXXXXXXXX"          # one video
python3 yt2mp3lrc.py "URL1" "URL2"                           # several
python3 yt2mp3lrc.py -f urls.txt                             # one URL per line
python3 yt2mp3lrc.py "https://www.youtube.com/playlist?list=XXXX"   # whole playlist
python3 yt2mp3lrc.py --force "URL"                           # redo even if already done
python3 yt2mp3lrc.py -o /media/sdcard/Music "URL"            # custom output folder
python3 yt2mp3lrc.py --no-sidecar "URL"                      # embed only: one file per song
python3 yt2mp3lrc.py --no-embed "URL"                        # .lrc sidecar only
python3 yt2mp3lrc.py --js-runtime node "URL"                 # use node because deno isn't installed
python3 yt2mp3lrc.py --cookies-from-browser firefox "URL"    # when YouTube bot-checks you
python3 yt2mp3lrc.py --player-client tv "URL"                # last-resort client swap
```

**Always quote your URLs.** Playlist links contain `&`, and an unquoted `&` makes the shell split
the command and silently drop half the URL.

**Where files go:** `Music/` **inside the current directory** — relative to where you run the
command, not to where the script lives. It prints the resolved path at startup. `Music/` is
gitignored, so nothing gets committed. Use `-o` to send them elsewhere.

Re-running is safe and cheap: whatever is already done is skipped, so you can point it at the same
folder every time you add music.

Output symbols: `->` working on · `+` wrote a file · `=` already done · `-` no lyrics found (normal
for instrumentals) · `!` failed.

## How the lyric matching works

Lyrics come from [LRCLIB](https://lrclib.net) (free, open, no account, no API key). Three passes:

1. **Exact lookup** — `artist + track + album + duration` against `/api/get`.
2. **Fuzzy search on track name** — the title as-is, then `&`↔`and` swapped, then with
   `(feat. ...)` removed.
3. **Free-text search** — `"artist track"`, duration window relaxed to ±5 s.

Every candidate must pass **all** of these guards:

- **Duration window** — ±3 s (±5 s on the last pass) against the video length. Stops a live version
  or extended edit matching the wrong recording.
- **Artist guard** — the LRCLIB artist must share a significant word with the expected artist.
- **Title guard** — on the free-text pass only, the candidate's title must share a word.

The artist guard exists because of a real bug found during testing, not theory. LRCLIB contains
unrelated songs that share a title *and* a near-identical duration:

| Video | Wrong match it used to take | Would have written |
|---|---|---|
| TheFatRat – Xenogenesis (235 s) | 3TEETH – Xenogenesis (233 s) | death-metal lyrics on an EDM instrumental |
| Jim Yosef – Firefly (227 s) | Mura Masa feat. NAO – Firefly (224 s) | unrelated R&B lyrics on a drum & bass track |

Title junk is stripped before matching (`(Official Music Video)`, `[NCS Release]`, `[4K UPGRADE]`,
`(Lyrics)`, `| Label | Genre` tails), and label channels (`NoCopyrightSounds`, `Monstercat`,
`Proximity`, ...) are never treated as the artist.

## What gets embedded

The ID3 `USLT` frame gets **readable text** — LRCLIB's plain lyrics, or the synced lyrics with the
`[mm:ss.xx]` prefixes stripped. Timestamps are deliberately *not* embedded: a player that shows
embedded lyrics as plain text would otherwise display bracket noise. The timing is the sidecar's job.

Audio is written with `-c copy`, so **the sound is bit-identical** before and after embedding
(verified by comparing the MD5 of the decoded PCM), and existing title/artist/album tags survive.

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
- **Sidecar naming**: standard is `Song.lrc` beside `Song.mp3` — what Poweramp, Musicolet,
  foobar2000, MusicBee, VLC, mpv and most DAPs expect. A few players look for `Song.mp3.lrc`; if one
  doesn't pick it up, copy the file under that name too.
- Single-video URLs skip the playlist probe, so a plain video costs one fewer request to YouTube —
  fewer requests means fewer bot checks.
- Lyrics are **offline** once downloaded. Budget DAPs fetch nothing themselves, which is why the
  `.lrc` sits in the folder.

## Files

| File | Purpose |
|---|---|
| `addlyrics.py` | attach lyrics to MP3s you already have (the recommended tool) |
| `yt2mp3lrc.py` | download from YouTube + attach lyrics; also holds the shared LRCLIB matching code |
| `test_addlyrics.py` | end-to-end tests for addlyrics.py (real LRCLIB, real ffmpeg) |
| `test_match.py` | artist/title guards (offline) + live LRCLIB matching |
| `requirements.txt` | `yt-dlp` (only needed for `yt2mp3lrc.py`, or `addlyrics.py --link`) |

## Verification status

`python3 test_match.py` → **ALL TESTS PASSED**
`python3 test_addlyrics.py` → **ALL ADDLYRICS TESTS PASSED**
(2026-09, Linux, ffmpeg 6.1.1, yt-dlp 2026.08.19)

### addlyrics.py

Asserted in `test_addlyrics.py`:

- Well-tagged file (Alan Walker / Faded, 212s) matched the right record; **decoded-audio MD5
  unchanged** by embedding; lyrics tag readable back out; title/artist/album preserved; `.lrc`
  written with matching basename.
- Junk channel-style artist tag (`ANN MUSIC`) → tag dropped, **correct** match (Alec Benjamin),
  and the title-only result **flagged** in the output.
- No tags at all → matched correctly from the filename.
- `--artist`/`--title` override junk tags.
- **Instrumental must be a clean miss:** TheFatRat – Xenogenesis (233s) must NOT match
  3TEETH – Xenogenesis (233s). Asserted.
- `--dry-run` changed nothing (verified by hashing).
- `--no-sidecar` leaves exactly one file.
- `.ogg` refused; re-runs skip; `--link` with multiple files errors.

### yt2mp3lrc.py

- **Lyrics are really in the MP3** (`USLT` frame present, words read back out, tags preserved,
  decoded-audio MD5 unchanged).
- **Timestamps don't leak into the tag** (`[00:` never appears in the embedded text).
- **Live LRCLIB matching on 9 real YouTube titles:** 6 vocal tracks matched with the right song's
  lyrics; 3 correctly returned nothing (2 instrumentals + 1 with no lyrics in LRCLIB).
- **Two false positives found and fixed** via the artist guard, both regression-tested.
- **Pipeline mechanics:** real download → ffmpeg MP3 → `.lrc` sidecar with matching basename;
  re-runs skip cleanly; `--no-sidecar` leaves exactly one file.
- **Failure messages:** bad URL, missing `yt-dlp`, missing `ffmpeg`, HTTP 403, wrong browser name and
  missing cookie file all produce actionable text instead of a traceback.
- **`--cookies-from-browser` / `--cookies` / `--player-client` / `--js-runtime` plumbed through**
  correctly (checked against yt-dlp's own `js_runtimes` validation).
- **JS runtime detection:** finds deno/node/bun/quickjs on PATH, quiet when deno is present,
  auto-enables the best available otherwise, warns clearly when none exists.
- **LRCLIB retries** transient 429/5xx with backoff (a live 503 was hit during testing and survived).

**Not verified:** the YouTube *download* step itself. From this datacenter IP every attempt fails at
the bot check ("Sign in to confirm you're not a bot") regardless of player client — deno/node as the
JS runtime, `web_safari`, `tv`, `android_vr` and `ios` all still refused. This is exactly why
`addlyrics.py` exists: everything except the download is tested, and the download is the part YouTube
is actively fighting.
