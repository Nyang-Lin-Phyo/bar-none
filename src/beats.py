"""Beat detection built on librosa.

``detect_beats`` loads an audio file, tracks its beats, and estimates which
beats are bar starts (downbeats).

Pipeline:

1. Beat tracking (librosa) on the onset-strength envelope.
2. Leading beats that march through a silent intro are dropped, so the
   first marker lands on the first audible hit.
3. Each beat is snapped onto a nearby onset peak (within 0.3 s) so markers
   sit on real transients instead of drifting between them.
4. Bar starts are picked by scoring every (beats-per-bar, phase) hypothesis
   against the *kick* band (40-150 Hz) — downbeats are where the heavy
   hits land, which full-band onset strength (hats, snares, melody)
   dilutes.  Scores are averaged across sections of the track so one loud
   passage cannot dominate, and the first hit after silence acts as a
   prior for the bar phase.

``detect_cut_points`` is the meter-free sibling for editing: it skips the
tempo/grid entirely and marks standalone *punch* moments (kick/snare
body) — one marker per strong hit, spaced at least ``min_gap`` apart —
for clips that should start/end on a hit rather than on a regular beat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import librosa
from scipy.ndimage import uniform_filter1d

HOP_LENGTH = 512
BAR_LENGTHS = (3, 4, 6)  # candidate beats per bar (3/4, 4/4, 6/8)

STFT_N_FFT = 2048
KICK_BAND = (40.0, 150.0)  # Hz — where the kick drum lives
SNAP_WINDOW = 0.30  # seconds — max move when snapping a beat to an onset
SNAP_IBI_FRACTION = 0.35  # …never past the midpoint toward the next beat
SNAP_MIN_SEP_FRACTION = 0.25  # snapped beats stay at least this fraction of an IBI apart
INTRO_ONSET_RATIO = 0.35  # onset strength counted as "strong" vs track peak
INTRO_RMS_RATIO = 0.40  # leading region must be this quiet vs track median
SECTION_BEATS = 48  # beats per scoring section (downbeat consensus)
SECTION_MIN_SD = 0.1  # sections quieter than this fraction of global sd: skip
PRIOR_BONUS = 0.5  # score boost for the phase holding the first hit
LAG4_TIE_RATIO = 0.9  # lag 4 wins unless another lag beats it by >10%

CUT_BAND = (40.0, 2500.0)  # Hz — kick/snare body: punch, not hat ticks
CUT_DENSITY_GAPS = {"tight": 0.5, "medium": 1.0, "loose": 1.5}  # seconds
DEFAULT_CUT_DENSITY = "medium"
PUNCH_BASELINE_SEC = 4.0  # window for the adaptive punch baseline
CUT_PEAK_MAX = 8  # frames (~0.19 s) peak neighbourhood for peak_pick
CUT_AVG = 32  # frames (~0.75 s) local baseline for peak_pick
CUT_PEAK_DELTA = 0.5  # punch must beat its local average by this much
CUT_PEAK_WAIT = 2  # frames between successive candidate peaks
CUT_RMS_RATIO = 0.25  # cuts must be at least this loud vs track median


@dataclass(frozen=True)
class BeatAnalysis:
    path: str
    tempo: float  # BPM
    beat_times: tuple[float, ...]  # seconds
    downbeat_indices: frozenset[int]  # 0-based positions into beat_times
    duration: float  # seconds

    @property
    def beat_count(self) -> int:
        return len(self.beat_times)

    @property
    def bar_count(self) -> int:
        return len(self.downbeat_indices)


@dataclass(frozen=True)
class CutAnalysis:
    """Meter-free punch points: candidate moments to cut a clip on."""

    path: str
    cut_times: tuple[float, ...]  # seconds
    duration: float  # seconds
    min_gap: float  # spacing used for this scan, in seconds

    @property
    def cut_count(self) -> int:
        return len(self.cut_times)


def detect_beats(
    path: str,
    progress: Callable[[str], None] | None = None,
) -> BeatAnalysis:
    """Detect beats (and bar starts) in an audio file."""

    def report(message: str) -> None:
        if progress is not None:
            progress(message)

    report("Loading audio…")
    y, sr = librosa.load(path, sr=22050, mono=True)
    duration = float(len(y) / sr)

    report("Tracking beats…")
    # aggregate=np.median matches what beat_track computes internally when
    # it builds the envelope itself — feeding it anything else changes the
    # tempo estimate and the whole grid.
    onset_env = librosa.onset.onset_strength(
        y=y, sr=sr, hop_length=HOP_LENGTH, aggregate=np.median
    )
    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=HOP_LENGTH,
        trim=False,
        units="frames",
    )
    beat_frames = np.asarray(beat_frames, dtype=int)
    if beat_frames.size == 0:
        raise RuntimeError("no beats could be detected in this file")

    beat_times = librosa.frames_to_time(
        beat_frames, sr=sr, hop_length=HOP_LENGTH
    )
    tempo_value = float(np.mean(np.atleast_1d(tempo)))

    rms = librosa.feature.rms(
        y=y, hop_length=HOP_LENGTH, frame_length=STFT_N_FFT
    )[0]
    beat_times, anchor = _trim_intro(beat_times, onset_env, rms, sr)
    punch = _punch_envelope(y, sr)
    beat_times = _snap_to_onsets(beat_times, punch, rms, sr)

    report("Finding downbeats…")
    downbeats = _find_downbeats(y, sr, beat_times, anchor=anchor)

    return BeatAnalysis(
        path=str(path),
        tempo=tempo_value,
        beat_times=tuple(float(t) for t in beat_times),
        downbeat_indices=downbeats,
        duration=duration,
    )


def _trim_intro(
    beat_times: np.ndarray,
    onset_env: np.ndarray,
    rms: np.ndarray,
    sr: int,
) -> tuple[np.ndarray, float | None]:
    """Drop leading beats that march through a silent intro.

    Returns ``(beat_times, anchor)`` where ``anchor`` is the time of the
    first strong onset when the leading region is genuinely quiet (it is
    used as the downbeat prior), else ``None``.
    """
    if beat_times.size == 0 or onset_env.size == 0 or rms.size == 0:
        return beat_times, None

    n = min(len(onset_env), len(rms))
    env, level = onset_env[:n], rms[:n]
    peak = float(env.max())
    if peak <= 0:
        return beat_times, None
    strong = np.flatnonzero(env >= INTRO_ONSET_RATIO * peak)
    if strong.size == 0 or strong[0] == 0:
        return beat_times, None

    first_strong = float(strong[0]) * HOP_LENGTH / sr
    track_rms = float(np.median(level))
    lead_rms = float(np.median(level[: strong[0]]))
    # Only trim when the region before the first strong hit is quiet —
    # a soft-but-real intro keeps its beats.
    if track_rms <= 0 or lead_rms >= INTRO_RMS_RATIO * track_rms:
        return beat_times, None

    ibi = (
        float(np.median(np.diff(beat_times)))
        if beat_times.size > 1
        else 0.5
    )
    kept = beat_times[beat_times >= first_strong - 0.5 * ibi]
    if kept.size < 8:  # never trim the grid away
        return beat_times, None
    return kept, first_strong


def _snap_to_onsets(
    beat_times: np.ndarray,
    punch: np.ndarray,
    rms: np.ndarray,
    sr: int,
) -> np.ndarray:
    """Pull each beat onto the strongest punch transient within ``SNAP_WINDOW``.

    Targets are peaks of the punch flux (40-2500 Hz) *itself* — not
    full-band onset peaks — so a beat moves to the strongest kick/snare
    transient near it and never onto a sharper-but-weak hat tick.  A beat
    only moves when the target is stronger than its current spot and
    sits on audible material, so markers never regress and silence keeps
    the plain grid.  The result stays strictly increasing (a snap that
    would collide keeps the grid position).
    """
    if beat_times.size < 2:
        return beat_times
    count = min(len(punch), len(rms))
    if count == 0:
        return beat_times
    punch, rms = punch[:count], rms[:count]
    floor = CUT_RMS_RATIO * float(np.median(rms))
    # The window must never reach the offbeat: at ±0.3 s a beat could hop
    # onto the next musical event (half-beats are ~0.31 s at 95 BPM),
    # which collapses neighbouring beats onto one transient and scrambles
    # the bar phase.  Clamp it to a fraction of the local beat interval.
    ibi = float(np.median(np.diff(beat_times)))
    window = max(
        1,
        int(
            round(
                min(SNAP_WINDOW, SNAP_IBI_FRACTION * ibi) * sr / HOP_LENGTH
            )
        ),
    )
    min_sep = max(1, int(round(SNAP_MIN_SEP_FRACTION * ibi * sr / HOP_LENGTH)))

    snapped: list[float] = []
    for t in beat_times:
        frame = int(
            np.clip(
                librosa.time_to_frames(t, sr=sr, hop_length=HOP_LENGTH),
                0,
                count - 1,
            )
        )
        lo, hi = max(0, frame - window), min(count, frame + window + 1)
        best = lo + int(np.argmax(punch[lo:hi]))
        here = float(punch[max(0, frame - 1) : min(count, frame + 2)].max())
        candidate = float(t)
        if punch[best] > here and rms[best] >= floor:
            candidate = best * HOP_LENGTH / sr
        if snapped and (candidate - snapped[-1]) * sr / HOP_LENGTH < min_sep:
            candidate = float(t)  # too close: keep the grid position
        if snapped and candidate <= snapped[-1]:
            candidate = float(t)  # keep order: prefer the grid position
        if snapped and candidate <= snapped[-1]:
            candidate = snapped[-1] + 1e-4  # pathological: force progress
        snapped.append(candidate)
    return np.asarray(snapped, dtype=float)


def _band_flux(y: np.ndarray, sr: int, low: float, high: float) -> np.ndarray:
    """Rectified frame-to-frame flux of one frequency band."""
    spectrum = np.abs(librosa.stft(y, n_fft=STFT_N_FFT, hop_length=HOP_LENGTH))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=STFT_N_FFT)
    band = spectrum[(freqs >= low) & (freqs <= high)].sum(axis=0)
    return np.maximum(0, np.diff(band, prepend=band[0]))


def _kick_envelope(y: np.ndarray, sr: int) -> np.ndarray:
    """Rectified flux of the kick band (40-150 Hz)."""
    return _band_flux(y, sr, KICK_BAND[0], KICK_BAND[1])


def _sample_at(envelope: np.ndarray, times: np.ndarray, sr: int) -> np.ndarray:
    """Envelope sampled at each time (max over ±1 frame)."""
    frames = np.clip(
        librosa.time_to_frames(
            np.asarray(times, dtype=float), sr=sr, hop_length=HOP_LENGTH
        ),
        0,
        len(envelope) - 1,
    ).astype(int)
    values = np.empty(len(frames), dtype=np.float64)
    for i, frame in enumerate(frames):
        lo, hi = max(0, frame - 1), min(len(envelope), frame + 2)
        values[i] = envelope[lo:hi].max()
    return values


def _bar_phase_scores(
    values: np.ndarray,
    prior_phase_of: Callable[[int], int] | None = None,
) -> list[tuple[float, int, int]]:
    """Score every (beats-per-bar, phase) hypothesis.

    The kick values are z-normalised *within* sections of the track and the
    per-section scores averaged, so a single loud passage cannot decide the
    meter on its own.  ``prior_phase_of(lag)`` names the phase that should
    get a bonus (the first hit after silence).
    """
    count = len(values)
    if count < 8:
        return []
    sections = np.array_split(np.arange(count), max(1, count // SECTION_BEATS))
    global_sd = float(values.std())

    scores: list[tuple[float, int, int]] = []
    for lag in BAR_LENGTHS:
        if count < lag * 2:
            continue
        for phase in range(lag):
            total, used = 0.0, 0
            for section in sections:
                section_values = values[section]
                mean = float(section_values.mean())
                sd = float(section_values.std())
                if sd <= 1e-12:
                    continue
                if global_sd > 0 and sd < SECTION_MIN_SD * global_sd:
                    continue  # near-silent section: no usable signal
                picks = section[section % lag == phase]
                if picks.size == 0:
                    continue
                z = (values[picks] - mean) / sd
                total += float(z.sum() / np.sqrt(picks.size))
                used += 1
            if used == 0:
                continue
            score = total / used
            if prior_phase_of is not None and phase == prior_phase_of(lag):
                score += PRIOR_BONUS
            scores.append((score, lag, phase))
    return scores


def _find_downbeats(
    y: np.ndarray,
    sr: int,
    beat_times: np.ndarray,
    anchor: float | None = None,
) -> frozenset[int]:
    """Pick the beat index that lines up with bar starts.

    Scores (bar length, phase) combinations against kick-band energy at
    each beat, with the first hit after silence as a phase prior.
    """
    count = len(beat_times)
    if count < 8:
        return frozenset()

    kick = _kick_envelope(y, sr)
    values = _sample_at(kick, beat_times, sr)

    prior_phase_of: Callable[[int], int] | None = None
    if anchor is not None:
        prior_idx = int(np.argmin(np.abs(beat_times - anchor)))
        prior_phase_of = lambda lag: prior_idx % lag  # noqa: E731

    scores = _bar_phase_scores(values, prior_phase_of)
    if not scores:
        return frozenset(range(0, count, 4))
    best = max(scores, key=lambda entry: entry[0])
    best_lag, best_phase = best[1], best[2]
    # 4/4 tie-break: a lag-6 score can win by subsampling only the strong
    # beats of a kick-on-1-and-3 pattern.  Unless another lag clearly beats
    # lag 4, count the track as 4/4 — by far the most common meter.
    lag4 = [entry for entry in scores if entry[1] == 4]
    if lag4:
        best_l4 = max(lag4, key=lambda entry: entry[0])
        if best_l4[0] <= 0 or best_l4[0] >= LAG4_TIE_RATIO * best[0]:
            best_lag, best_phase = 4, best_l4[2]
    return frozenset(range(best_phase, count, best_lag))


# ------------------------------------------------------------- cut points


def _punch_envelope(y: np.ndarray, sr: int) -> np.ndarray:
    """Punch flux (40-2500 Hz) normalised by its own ~4 s baseline.

    Dividing by a local average makes the score section-adaptive: a soft
    fill still registers in a quiet verse, and a loud drop cannot drown
    the rest of the track in candidates.
    """
    flux = _band_flux(y, sr, CUT_BAND[0], CUT_BAND[1])
    window = max(3, int(round(PUNCH_BASELINE_SEC * sr / HOP_LENGTH)))
    baseline = uniform_filter1d(flux, size=window, mode="nearest")
    return flux / (baseline + 0.1 * float(flux.mean()) + 1e-12)


def find_cut_points(y: np.ndarray, sr: int, min_gap: float) -> np.ndarray:
    """Find standalone punch moments where a cut would land.

    Meter-free: every marker is placed independently on a peak of the
    punch band.  A candidate must stand out above its local baseline
    (``CUT_PEAK_DELTA``), sit on audible material (RMS floor vs the
    track median, so silence earns no markers), and be at least
    ``min_gap`` seconds apart — strongest hits win the spacing contests,
    then the survivors are ordered in time.
    """
    punch = _punch_envelope(y, sr)
    rms = librosa.feature.rms(
        y=y, hop_length=HOP_LENGTH, frame_length=STFT_N_FFT
    )[0]
    count = min(len(punch), len(rms))
    if count == 0:
        return np.empty(0)
    punch, rms = punch[:count], rms[:count]

    peaks = librosa.util.peak_pick(
        punch,
        pre_max=CUT_PEAK_MAX,
        post_max=CUT_PEAK_MAX,
        pre_avg=CUT_AVG,
        post_avg=CUT_AVG,
        delta=CUT_PEAK_DELTA,
        wait=CUT_PEAK_WAIT,
    )
    if peaks.size == 0:
        return np.empty(0)

    floor = CUT_RMS_RATIO * float(np.median(rms))
    peaks = peaks[rms[peaks] >= floor]
    if peaks.size == 0:
        return np.empty(0)

    strongest_first = peaks[np.argsort(punch[peaks])[::-1]]
    gap_frames = float(min_gap) * sr / HOP_LENGTH
    chosen: list[int] = []
    for frame in strongest_first:
        if all(abs(int(frame) - kept) >= gap_frames for kept in chosen):
            chosen.append(int(frame))
    if not chosen:
        return np.empty(0)
    return np.asarray(sorted(chosen), dtype=float) * HOP_LENGTH / sr


def detect_cut_points(
    path: str,
    min_gap: float | None = None,
    progress: Callable[[str], None] | None = None,
) -> CutAnalysis:
    """Find meter-free cut points (punchy hits) in an audio file."""
    gap = (
        CUT_DENSITY_GAPS[DEFAULT_CUT_DENSITY]
        if min_gap is None
        else float(min_gap)
    )
    if gap <= 0:
        raise ValueError("min_gap must be positive")

    def report(message: str) -> None:
        if progress is not None:
            progress(message)

    report("Loading audio…")
    y, sr = librosa.load(path, sr=22050, mono=True)
    duration = float(len(y) / sr)

    report("Scoring punch points…")
    cuts = find_cut_points(y, sr, gap)
    if cuts.size == 0:
        raise RuntimeError("no punch points could be detected in this file")

    return CutAnalysis(
        path=str(path),
        cut_times=tuple(float(t) for t in cuts),
        duration=duration,
        min_gap=gap,
    )
