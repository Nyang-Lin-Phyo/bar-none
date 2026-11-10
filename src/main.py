#!/usr/bin/env python3
"""beatMatcher — turn the beats of a music file into a DaVinci Resolve EDL.

Usage:
    python src/main.py                     # GUI (needs tkinter)
    python src/main.py TRACK.mp3 [options] # headless CLI export
    python src/main.py --help              # CLI options
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SRC_DIR)
sys.path.insert(0, SRC_DIR)

from beats import BeatAnalysis, detect_beats
from edl import MODE_ALL, MODE_BOTH, MODE_DOWNBEATS, build_edl, make_markers
from timecode import (
    DEFAULT_CLIP_SOURCE_TC,
    DEFAULT_FRAME_RATE_LABEL,
    DEFAULT_TIMELINE_START_TC,
    FRAME_RATES,
    get_frame_rate,
    parse_timecode,
)

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    import theme

    TK_AVAILABLE = True
except ImportError:
    tk = filedialog = messagebox = ttk = theme = None  # type: ignore[assignment]
    TK_AVAILABLE = False

# Label shown in the GUI -> mode constant
MODE_CHOICES = {
    "Both (bars + beats)": MODE_BOTH,
    "All beats": MODE_ALL,
    "Downbeats only": MODE_DOWNBEATS,
}

AUDIO_FILETYPES = [
    ("Audio files", "*.mp3 *.wav *.flac *.ogg *.m4a *.aac *.aiff *.aif"),
    ("All files", "*.*"),
]


def format_duration(seconds: float) -> str:
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if any(key in lowered for key in ("format", "backend", "codec", "ffmpeg", "audioread")):
        text += (
            "\n\nHint: this audio format could not be decoded. "
            "Installing ffmpeg usually fixes it — "
            "Windows: winget install ffmpeg · Linux: sudo apt install ffmpeg"
        )
    return text


class BeatMatcherApp:
    POLL_MS = 100

    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        root.title("beatMatcher")
        root.minsize(700, 480)

        # theme state — toggled by the tag button, top-right
        self.theme_name = "dark"
        self.palette = theme.DARK
        self.serif, self.mono = theme.pick_fonts(root)
        self.style = ttk.Style(root)
        theme.init_style(self.style)
        theme.apply(root, self.style, self.palette, self.serif, self.mono)

        self.audio_path: str | None = None
        self.analysis: BeatAnalysis | None = None
        self._detecting = False
        self._messages: "queue.Queue[object]" = queue.Queue()

        # All state lives in StringVars so a theme rebuild keeps it intact.
        self.file_var = tk.StringVar(value="No file selected yet.")
        self.status_var = tk.StringVar(
            value="Choose a music file, then press Detect beats."
        )
        self.bpm_var = tk.StringVar(value="—")
        self.beats_var = tk.StringVar(value="—")
        self.bars_var = tk.StringVar(value="—")
        self.length_var = tk.StringVar(value="—")
        self.mode_var = tk.StringVar(value=next(iter(MODE_CHOICES)))
        self.rate_var = tk.StringVar(value=DEFAULT_FRAME_RATE_LABEL)
        self.source_tc_var = tk.StringVar(value=DEFAULT_CLIP_SOURCE_TC)
        self.timeline_tc_var = tk.StringVar(value=DEFAULT_TIMELINE_START_TC)
        self.title_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(value="")

        self._build_ui()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        p = self.palette
        mono, serif = self.mono, self.serif
        root = self.root
        root.configure(bg=p["bg"])

        # ── header: serif wordmark + theme tag ────────────────────────
        header = tk.Frame(root, bg=p["bg"])
        header.pack(fill="x", padx=20, pady=(16, 0))
        wordmark = tk.Frame(header, bg=p["bg"])
        wordmark.pack(side="left")
        tk.Label(
            wordmark, text="beatMatcher", bg=p["bg"], fg=p["purple"],
            font=(serif, 26),
        ).pack(anchor="w")
        tk.Label(
            wordmark, text="MUSIC BEATS → DAVINCI RESOLVE MARKERS",
            bg=p["bg"], fg=p["muted"], font=(mono, 8),
        ).pack(anchor="w")
        ttk.Button(
            header,
            text="LIGHT" if self.theme_name == "dark" else "DARK",
            style="Tag.TButton",
            command=self._toggle_theme,
        ).pack(side="right", pady=(4, 0))

        # ── 01 — SOURCE ───────────────────────────────────────────────
        self._section("01 — SOURCE")
        source = tk.Frame(root, bg=p["bg"])
        source.pack(fill="x", padx=20)

        file_row = tk.Frame(source, bg=p["bg"])
        file_row.pack(fill="x")
        ttk.Button(
            file_row, text="CHOOSE AUDIO FILE…", command=self._choose_file
        ).pack(side="left")
        tk.Label(
            file_row, textvariable=self.file_var, bg=p["bg"], fg=p["text"],
            font=(mono, 9), anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(12, 0))

        action_row = tk.Frame(source, bg=p["bg"])
        action_row.pack(fill="x", pady=(10, 0))
        self.detect_btn = ttk.Button(
            action_row,
            text="DETECT BEATS",
            style="Primary.TButton",
            command=self._start_detection,
        )
        self.detect_btn.pack(side="left")
        if self._detecting:
            self.detect_btn.state(["disabled"])

        # ── 02 — RESULT ───────────────────────────────────────────────
        self._section("02 — RESULT")
        card = tk.Frame(
            root, bg=p["bg2"], highlightbackground=p["line"],
            highlightthickness=1,
        )
        card.pack(fill="x", padx=20)
        readouts = (
            ("BPM", self.bpm_var),
            ("BEATS", self.beats_var),
            ("BARS", self.bars_var),
            ("LENGTH", self.length_var),
        )
        for column, (label, variable) in enumerate(readouts):
            card.columnconfigure(column, weight=1)
            cell = tk.Frame(card, bg=p["bg2"])
            cell.grid(
                row=0, column=column, sticky="nsew", padx=(18, 18), pady=(13, 13)
            )
            tk.Label(
                cell, text=label, bg=p["bg2"], fg=p["muted"], font=(mono, 8)
            ).pack(anchor="w")
            tk.Label(
                cell, textvariable=variable, bg=p["bg2"], fg=p["purple"],
                font=(serif, 28),
            ).pack(anchor="w")

        # ── 03 — MARKERS ──────────────────────────────────────────────
        self._section("03 — MARKERS")
        options = tk.Frame(root, bg=p["bg"])
        options.pack(fill="x", padx=20)
        options.columnconfigure(1, weight=1)
        options.columnconfigure(3, weight=1)

        self._field(options, 0, 0, "MARKER MODE")
        ttk.Combobox(
            options,
            textvariable=self.mode_var,
            values=list(MODE_CHOICES),
            state="readonly",
            width=24,
        ).grid(row=0, column=1, sticky="w", padx=(0, 18), pady=5)

        self._field(options, 0, 2, "FRAME RATE")
        ttk.Combobox(
            options,
            textvariable=self.rate_var,
            values=[rate.label for rate in FRAME_RATES],
            state="readonly",
            width=8,
        ).grid(row=0, column=3, sticky="w", pady=5)

        self._field(options, 1, 0, "MUSIC START ON TIMELINE")
        ttk.Entry(
            options, textvariable=self.timeline_tc_var, width=16
        ).grid(row=1, column=1, sticky="w", padx=(0, 18), pady=5)

        self._field(options, 1, 2, "CLIP SOURCE TC")
        ttk.Entry(
            options, textvariable=self.source_tc_var, width=16
        ).grid(row=1, column=3, sticky="w", pady=5)

        tk.Label(
            options,
            text=(
                "Both mode: bars are red markers, beats are blue markers.\n"
                "“Music start on timeline” = where the music sits on the "
                "timeline you'll import markers onto."
            ),
            bg=p["bg"], fg=p["muted"], font=(mono, 8), justify="left",
            wraplength=620,
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        # ── 04 — EXPORT ───────────────────────────────────────────────
        self._section("04 — EXPORT")
        export = tk.Frame(root, bg=p["bg"])
        export.pack(fill="x", padx=20)
        export.columnconfigure(1, weight=1)

        self._field(export, 0, 0, "TIMELINE TITLE")
        ttk.Entry(export, textvariable=self.title_var).grid(
            row=0, column=1, sticky="we", pady=5
        )

        self._field(export, 1, 0, "OUTPUT FILE")
        output_row = tk.Frame(export, bg=p["bg"])
        output_row.grid(row=1, column=1, sticky="we", pady=5)
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_var).grid(
            row=0, column=0, sticky="we"
        )
        ttk.Button(
            output_row, text="BROWSE…", command=self._choose_output
        ).grid(row=0, column=1, padx=(8, 0))

        self.export_btn = ttk.Button(
            export,
            text="EXPORT EDL",
            style="Primary.TButton",
            command=self._export,
        )
        self.export_btn.grid(row=2, column=1, sticky="w", pady=(12, 0))
        if self.analysis is None or self._detecting:
            self.export_btn.state(["disabled"])

        # ── footer status bar ─────────────────────────────────────────
        tk.Frame(root, bg=p["line"], height=1).pack(
            fill="x", padx=20, pady=(18, 0)
        )
        footer = tk.Frame(root, bg=p["bg"])
        footer.pack(fill="x", padx=20, pady=(8, 14))
        tk.Label(
            footer, textvariable=self.status_var, bg=p["bg"], fg=p["text"],
            font=(mono, 9), anchor="w",
        ).pack(fill="x")

    def _section(self, text: str) -> None:
        """Tiny uppercase label with a hairline rule, like the site's section labels."""
        p = self.palette
        row = tk.Frame(self.root, bg=p["bg"])
        row.pack(fill="x", padx=20, pady=(18, 7))
        tk.Label(
            row, text=text, bg=p["bg"], fg=p["purple_dim"], font=(self.mono, 8)
        ).pack(side="left")
        tk.Frame(row, bg=p["line"], height=1).pack(
            side="left", fill="x", expand=True, padx=(12, 0), pady=4
        )

    def _field(self, parent: "tk.Frame", row: int, column: int, text: str) -> None:
        """Muted uppercase field label, like the site's .detail-key rows."""
        tk.Label(
            parent,
            text=text,
            bg=self.palette["bg"],
            fg=self.palette["muted"],
            font=(self.mono, 9),
        ).grid(row=row, column=column, sticky="w", padx=(0, 8), pady=5)

    def _toggle_theme(self) -> None:
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.palette = theme.LIGHT if self.theme_name == "light" else theme.DARK
        theme.apply(self.root, self.style, self.palette, self.serif, self.mono)
        for child in self.root.winfo_children():
            child.destroy()
        self._build_ui()

    # -------------------------------------------------------------- actions

    def _choose_file(self) -> None:
        initial_dir = os.path.join(PROJECT_ROOT, "examples")
        if not os.path.isdir(initial_dir):
            initial_dir = PROJECT_ROOT
        path = filedialog.askopenfilename(
            title="Choose a music file",
            initialdir=initial_dir,
            filetypes=AUDIO_FILETYPES,
        )
        if not path:
            return
        self.audio_path = path
        self.analysis = None
        self.file_var.set(path)
        self.detect_btn.state(["!disabled"])
        self.export_btn.state(["disabled"])

        stem = os.path.splitext(os.path.basename(path))[0]
        self.title_var.set(stem)
        self.output_var.set(os.path.join(PROJECT_ROOT, "edlFiles", stem + ".edl"))
        self.bpm_var.set("—")
        self.beats_var.set("—")
        self.bars_var.set("—")
        self.length_var.set("—")
        self.status_var.set("Ready — press Detect beats.")

    def _choose_output(self) -> None:
        current = self.output_var.get().strip()
        initial_dir = os.path.dirname(current) if current else os.path.join(
            PROJECT_ROOT, "edlFiles"
        )
        initial_file = os.path.basename(current) if current else "timeline.edl"
        path = filedialog.asksaveasfilename(
            title="Save EDL as",
            initialdir=initial_dir if os.path.isdir(initial_dir) else PROJECT_ROOT,
            initialfile=initial_file,
            defaultextension=".edl",
            filetypes=[("EDL files", "*.edl"), ("All files", "*.*")],
        )
        if path:
            self.output_var.set(path)

    def _start_detection(self) -> None:
        if not self.audio_path:
            messagebox.showwarning("No file", "Choose a music file first.")
            return
        self._detecting = True
        self.analysis = None
        self.detect_btn.state(["disabled"])
        self.export_btn.state(["disabled"])
        self.root.config(cursor="watch")
        self.status_var.set("Starting…")
        threading.Thread(target=self._detect_worker, daemon=True).start()
        self.root.after(self.POLL_MS, self._poll)

    def _detect_worker(self) -> None:
        assert self.audio_path is not None
        try:
            analysis = detect_beats(self.audio_path, progress=self._messages.put)
        except Exception as exc:  # noqa: BLE001 - surfaced in a dialog
            self._messages.put(("error", exc))
        else:
            self._messages.put(("done", analysis))

    def _poll(self) -> None:
        try:
            while True:
                self._handle_message(self._messages.get_nowait())
        except queue.Empty:
            pass
        if self._detecting:
            self.root.after(self.POLL_MS, self._poll)

    def _handle_message(self, message: object) -> None:
        if isinstance(message, tuple):
            kind, payload = message
            if kind == "done":
                self._finish_detection(payload)  # type: ignore[arg-type]
            else:
                self._fail_detection(payload)  # type: ignore[arg-type]
        else:
            self.status_var.set(str(message))

    def _finish_detection(self, analysis: BeatAnalysis) -> None:
        self._detecting = False
        self.analysis = analysis
        self.detect_btn.state(["!disabled"])
        self.export_btn.state(["!disabled"])
        self.root.config(cursor="")
        self.bpm_var.set(f"{analysis.tempo:.1f}")
        self.beats_var.set(str(analysis.beat_count))
        self.bars_var.set(str(analysis.bar_count))
        self.length_var.set(format_duration(analysis.duration))
        self.status_var.set(
            f"{analysis.beat_count} beats / {analysis.bar_count} bars at "
            f"{analysis.tempo:.1f} BPM — pick options, then Export EDL."
        )

    def _fail_detection(self, exc: BaseException) -> None:
        self._detecting = False
        self.detect_btn.state(["!disabled"])
        self.root.config(cursor="")
        self.status_var.set("Beat detection failed.")
        messagebox.showerror("Beat detection failed", format_error(exc))

    def _export(self) -> None:
        if self.analysis is None or not self.audio_path:
            messagebox.showwarning("Nothing to export", "Detect beats first.")
            return

        try:
            rate = get_frame_rate(self.rate_var.get())
            source_tc = self.source_tc_var.get().strip()
            timeline_tc = self.timeline_tc_var.get().strip()
            parse_timecode(source_tc, rate)
            parse_timecode(timeline_tc, rate)
        except ValueError as exc:
            messagebox.showerror("Bad setting", str(exc))
            return

        mode = MODE_CHOICES[self.mode_var.get()]
        markers = make_markers(
            self.analysis.beat_times, self.analysis.downbeat_indices, mode
        )
        if not markers:
            messagebox.showwarning(
                "No markers",
                "This mode produced no markers for this track — "
                "try “All beats” instead.",
            )
            return

        title = self.title_var.get().strip() or os.path.splitext(
            os.path.basename(self.audio_path)
        )[0]
        text = build_edl(
            title,
            markers,
            rate,
            clip_source_tc=source_tc,
            timeline_start_tc=timeline_tc,
        )

        path = self.output_var.get().strip()
        if not path:
            messagebox.showerror("No output file", "Choose where to save the EDL.")
            return
        if os.path.exists(path):
            overwrite = messagebox.askyesno(
                "Overwrite?",
                f"{os.path.basename(path)} already exists.\nOverwrite it?",
            )
            if not overwrite:
                return
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(text.encode("utf-8"))
        except OSError as exc:
            messagebox.showerror("Could not write file", str(exc))
            return

        self.status_var.set(f"Wrote {len(markers)} markers → {path}")
        messagebox.showinfo(
            "Exported",
            f"Wrote {len(markers)} markers to:\n{path}\n\n"
            "In Resolve — puts markers on a timeline you already have:\n"
            "  1. Media page: select your timeline in the Media Pool\n"
            "  2. Timelines → Import → Timeline Markers from EDL…\n"
            "  3. Choose this file\n\n"
            "Do NOT use File → Import → Timeline — that builds a new "
            "timeline out of 1-frame cuts.\n\n"
            "“Music start on timeline” must match where the music sits "
            "on that timeline.",
        )


def run_gui() -> int:
    if not TK_AVAILABLE:
        print("error: Tkinter is not available in this Python.", file=sys.stderr)
        print("It is not a pip package. Install it with:", file=sys.stderr)
        print("    Linux:   sudo apt install python3-tk", file=sys.stderr)
        print("    Windows: use the python.org installer (tcl/tk is included),", file=sys.stderr)
        print("             or enable “tcl/tk and IDLE” if repairing Python.", file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"error: could not open a window ({exc}).", file=sys.stderr)
        print(
            "On a headless machine use the CLI instead: python src/main.py --help",
            file=sys.stderr,
        )
        return 1
    BeatMatcherApp(root)
    root.mainloop()
    return 0


def run_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="beatMatcher",
        description=(
            "Detect beats in a music file and export a DaVinci Resolve EDL "
            "with a marker per beat."
        ),
    )
    parser.add_argument("file", help="music file (mp3 / wav / flac / …)")
    parser.add_argument(
        "--mode",
        choices=[MODE_ALL, MODE_DOWNBEATS, MODE_BOTH],
        default=MODE_BOTH,
        help="which beats become markers (default: both)",
    )
    parser.add_argument(
        "--fps",
        default=DEFAULT_FRAME_RATE_LABEL,
        choices=[rate.label for rate in FRAME_RATES],
        help="timeline frame rate (default: %(default)s)",
    )
    parser.add_argument(
        "--source-tc",
        default=DEFAULT_CLIP_SOURCE_TC,
        help="timecode of the clip's first frame (default: %(default)s)",
    )
    parser.add_argument(
        "--start-tc",
        default=DEFAULT_TIMELINE_START_TC,
        help="where the music sits on the timeline (default: %(default)s)",
    )
    parser.add_argument("--title", default=None, help="EDL TITLE (default: file name)")
    parser.add_argument(
        "--out", default=None, help="output .edl path (default: edlFiles/<file>.edl)"
    )
    args = parser.parse_args(argv)

    def report(message: str) -> None:
        print(f"  {message}", flush=True)

    try:
        analysis = detect_beats(args.file, progress=report)
        rate = get_frame_rate(args.fps)
        markers = make_markers(
            analysis.beat_times, analysis.downbeat_indices, args.mode
        )
        if not markers:
            raise RuntimeError(f"no markers for mode {args.mode!r}")
        title = args.title or os.path.splitext(os.path.basename(args.file))[0]
        text = build_edl(
            title,
            markers,
            rate,
            clip_source_tc=args.source_tc,
            timeline_start_tc=args.start_tc,
        )
        out = args.out or os.path.join(PROJECT_ROOT, "edlFiles", title + ".edl")
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "wb") as handle:
            handle.write(text.encode("utf-8"))
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"error: {format_error(exc)}", file=sys.stderr)
        return 1

    print(
        f"{analysis.tempo:.1f} BPM · {analysis.beat_count} beats · "
        f"{analysis.bar_count} bars · {format_duration(analysis.duration)}"
    )
    print(f"{len(markers)} markers → {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return run_gui()
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
