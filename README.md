# Bar None

Drop in a music file, get an EDL out. The EDL contains one 1-frame event per
beat, each carrying a Resolve marker — import it with Resolve's
*Timelines → Import → Timeline Markers from EDL* and **your existing
timeline** gets markers exactly where the beats are, so you can snap clip
start/end points to them. No new timeline is created.

## Get the app (Windows)

Download `BarNone-1.0.0-win.zip` from the GitHub release, then:

1. **Unzip** it anywhere (Desktop, a USB stick — no installer, no admin).
2. Double-click **`BarNone.exe`**.
3. First run? Windows SmartScreen may say *"Windows protected your PC"* —
   the exe is unsigned, so this is expected. Click **More info →
   Run anyway**. (`BarNone-cli.exe` is the same app for the terminal.)

The whole folder is the app: delete the folder and it's gone — nothing
left in the registry, no traces.

## Setup (run from source)

### Windows

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
     *All beats*, *Downbeats only*, or *Cut points* (meter-free markers
     on punchy hits — red `Cut 1…`, one per strong kick/snare).
   - **Cut spacing** — for *Cut points*: *Tight* (0.5 s apart),
     *Medium* (1.0 s), *Loose* (1.5 s). Changing mode or spacing makes
     you press Detect again.
   - **Frame rate** — must match your Resolve timeline (default `24`).
   - **Clip source TC** — timecode of the audio clip's first frame
     (default `01:00:00:00`).
   - **Music start on timeline** — where the music sits on the timeline
     you'll import markers onto (default `01:00:00:00`). Markers are placed
     relative to this — this is the setting that makes them land on your
     beats.
   - **Timeline title** / **Output file** — defaults to the track name,
     from source it saves under `edlFiles/`, from the Windows app under
     your Documents folder.
4. **EXPORT EDL**.

The **LIGHT / DARK** tag, top-right, flips between the two themes (dark is
the default, matching the site).

### CLI equivalent

```bash
# beat grid markers
python src/main.py "examples/raph - alright (official audio).mp3" \
    --mode both --fps 24 --start-tc 01:00:00:00

# meter-free cut points, 1.0 s apart (medium)
python src/main.py "examples/raph - alright (official audio).mp3" \
    --mode cut --density medium --fps 24
```

## Import markers into YOUR existing DaVinci Resolve timeline

Do **not** use *File → Import → Timeline…* — that builds a new timeline out
of 1-frame cuts. The correct path puts markers on a timeline you already
have:

1. In the **Media** page, **select your timeline** in the Media Pool.
2. Right-click it → **Timelines → Import → Timeline Markers from EDL…**
3. Pick the exported `.edl` — markers appear on that timeline at their
   timecode positions (`Beat 1…` blue, `Bar 1…` red in *Both* mode,
   `Cut 1…` red in *Cut points* mode).

**Before exporting**, set *Music start on timeline* to wherever the music
actually sits on that timeline (default `01:00:00:00`), and keep *Frame rate*
matching your project (24 by default).

Troubleshooting:

- **No markers visible?** Make sure the timeline is selected in the Media
  Pool before importing, then zoom out — markers outside the visible range
  appear once you zoom out.
- Marker names must be ASCII — ours are (`Beat 12`, `Bar 3`, `Cut 7`).
- **Markers off by a constant amount?** The *Music start on timeline* value
  doesn't match where the music sits — fix it and re-import.

## How it works

- **Beats** — `librosa.beat.beat_track` (tempo + beat times), then:
  leading beats over a silent intro are dropped (first marker lands on the
  first audible hit) and each beat is snapped onto the strongest *punch*
  transient (40–2500 Hz) within 0.3 s — never past the midpoint to the
  next beat, never onto a hat tick, never onto silence.
- **Downbeats** — scored on the *kick band* (40–150 Hz), where the heavy
  hits live: the (bar length ∈ 3/4/6, phase) combination with the strongest
  kick energy wins, averaged across track sections so one loud passage
  can't decide the meter alone, with the first hit after silence as a
  phase prior and a near-tie fallback to 4/4.
- **Cut points** — no tempo, no meter: every marker is placed
  independently on a peak of the punch band (kick/snare body, not hat
  ticks), standing out above its local 4 s baseline, on audible material
  (silence earns no markers), at least *Cut spacing* apart — strongest
  hits win the spacing contests.
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
python -m unittest discover tests
```

19 tests: EDL byte-format (including a byte-for-byte regeneration of the
reference `edlFiles/Timeline 1.edl` — that file is gitignored, so restore
it from a previous run or export one before running) and cut-point
detection (spacing, silence, marker naming).

## Build the Windows app

PyInstaller only builds for the OS it runs on, so this needs a Windows
machine (or VM). From the repo root:

```bat
packaging\build.bat
```

That creates `.venv`, installs `requirements.txt` + `requirements-dev.txt`,
and runs PyInstaller with `packaging\barnone.spec`. Output:

```
dist\BarNone\
  BarNone.exe        # GUI, no console window
  BarNone-cli.exe    # console build of the same app
  _internal\         # runtime (librosa, numba, assets, …)
```

Zip the whole `dist\BarNone` folder and that's the release artifact.
The exes carry version info (Bar None / generic cat / 1.0.0) and the
app icon; the built folder is ~290 MB — librosa + numba are heavy.

```powershell
# from the repo root, after the build
Compress-Archive -Path dist\BarNone -DestinationPath BarNone-1.0.0-win.zip
Get-FileHash -Algorithm SHA256 BarNone-1.0.0-win.zip   # paste into the release notes
```

Upload the zip to the GitHub release and list its SHA256 so downloads can
be verified. (`build/`, `dist/`, `.venv/` and `BarNone-*.zip` are
gitignored; `assets/` is committed — the icon is needed by both the build
and source runs, and `packaging/make_icon.py` regenerates it from the
artwork.)

To regenerate the icon from the artwork after edits (stdlib only, no
Pillow needed):

```bash
python packaging/make_icon.py
```

## Layout

```
src/
  main.py       # Tkinter GUI + CLI entry point (frozen-exe aware)
  theme.py      # site palette (dark/light) + ttk styling + font fallbacks
  beats.py      # librosa beat/downbeat/cut-point detection
  timecode.py   # seconds ⇄ SMPTE timecode
  edl.py        # marker model + EDL writer
tests/
  test_edl_format.py   # EDL byte format + timecode
  test_cut_points.py   # cut-point detection
packaging/
  barnone.spec        # PyInstaller spec (GUI + CLI exe)
  build.bat           # one-command Windows build
  make_icon.py        # artwork → icon.ico / icon.png (stdlib only)
  version_info*.py    # exe version resources
assets/
  B N.png       # source artwork
  icon.ico      # generated (multi-size, transparent)
  icon.png      # generated (256 px window icon)
edlFiles/       # exports land here (source runs)
examples/       # sample tracks (gitignored)
```
