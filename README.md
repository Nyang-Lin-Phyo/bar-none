# beatMatcher

Drop in a music file, get an EDL out. The EDL contains one 1-frame event per
beat, each carrying a Resolve marker — import it with Resolve's
*Timelines → Import → Timeline Markers from EDL* and **your existing
timeline** gets markers exactly where the beats are, so you can snap clip
start/end points to them. No new timeline is created.

## Setup

### Windows (target platform)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Tkinter ships with the python.org installer — nothing extra needed.

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
sudo apt install python3-tk    # Linux only — Tk is a system package here
```

If MP3s ever fail to decode, install ffmpeg too
(`winget install ffmpeg` on Windows, `sudo apt install ffmpeg` on Linux).

## Run

```bash
# Windows
.venv\Scripts\activate
python src\main.py

# Linux / macOS
source .venv/bin/activate
python src/main.py
```

`python src/main.py --help` runs the headless CLI (works without tkinter).

## Use

1. **CHOOSE AUDIO FILE…** — `examples/` has three test tracks.
2. **DETECT BEATS** — shows BPM, beat count, bar count, and length.
3. Options:
   - **Marker mode** — *Both (bars + beats)* (red bars, blue beats),
     *All beats*, or *Downbeats only*.
   - **Frame rate** — must match your Resolve timeline (default `24`).
   - **Clip source TC** — timecode of the audio clip's first frame
     (default `01:00:00:00`).
   - **Music start on timeline** — where the music sits on the timeline
     you'll import markers onto (default `01:00:00:00`). Markers are placed
     relative to this — this is the setting that makes them land on your
     beats.
   - **Timeline title** / **Output file** — defaults to the track name,
     saved under `edlFiles/`.
4. **EXPORT EDL**.

The **LIGHT / DARK** tag, top-right, flips between the two themes (dark is
the default, matching the site).

### CLI equivalent

```bash
python src/main.py "examples/raph - alright (official audio).mp3" \
    --mode both --fps 24 --start-tc 01:00:00:00
```

## Import markers into YOUR existing DaVinci Resolve timeline

Do **not** use *File → Import → Timeline…* — that builds a new timeline out
of 1-frame cuts. The correct path puts markers on a timeline you already
have:

1. In the **Media** page, **select your timeline** in the Media Pool.
2. Right-click it → **Timelines → Import → Timeline Markers from EDL…**
3. Pick the exported `.edl` — markers appear on that timeline at their
   timecode positions (`Beat 1…` blue, `Bar 1…` red in *Both* mode).

**Before exporting**, set *Music start on timeline* to wherever the music
actually sits on that timeline (default `01:00:00:00`), and keep *Frame rate*
matching your project (24 by default).

Troubleshooting:

- **No markers visible?** Make sure the timeline is selected in the Media
  Pool before importing, then zoom out — markers outside the visible range
  appear once you zoom out.
- Marker names must be ASCII — ours are (`Beat 12`, `Bar 3`).
- **Markers off by a constant amount?** The *Music start on timeline* value
  doesn't match where the music sits — fix it and re-import.

## How it works

- **Beats** — `librosa.beat.beat_track` (tempo + beat times in seconds).
- **Downbeats** — onset strength sampled at each beat; the (bar length ∈
  3/4/6, phase) combination with the strongest consistent peaks wins.
- **Timecode** — `frames = round(seconds × fps)`; non-drop `HH:MM:SS:FF`
  counted at the nominal rate (23.976 → 24, 29.97 → 30).
- **EDL** — CMX3600-style, Resolve flavour: CRLF line endings, event line
  with two trailing spaces, marker on the continuation line as
  `|C:<color> |M:<name> |D:1` — byte-compatible with the reference
  `edlFiles/Timeline 1.edl`.

## Look & feel

The UI is themed from [nyang-lin-phyo.github.io](https://nyang-lin-phyo.github.io/personalWebsite/index.html):
near-black `#0d0b14` background, lavender `#d4b8ff` accent, light serif
display type (Cormorant Garamond → Georgia fallback) over mono body text
(DM Mono → Consolas fallback), hairline section rules, and a light theme
(`#f4f1fb` / `#573bb5`) mirroring the site's `data-theme="light"` tokens.

## Tests

```bash
python tests/test_edl_format.py
```

14 tests, including a byte-for-byte regeneration of the reference
`edlFiles/Timeline 1.edl`.

## Layout

```
src/
  main.py       # Tkinter GUI + CLI entry point
  theme.py      # site palette (dark/light) + ttk styling + font fallbacks
  beats.py      # librosa beat/downbeat detection
  timecode.py   # seconds ⇄ SMPTE timecode
  edl.py        # marker model + EDL writer
tests/
  test_edl_format.py
edlFiles/       # exports land here
examples/       # sample tracks
```
