"""Beat detection built on librosa.

``detect_beats`` loads an audio file, tracks its beats, and estimates which
beats are bar starts (downbeats) by looking for the beat index whose onset
strengths peak most consistently every 3/4/6 beats.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import librosa

HOP_LENGTH = 512
BAR_LENGTHS = (3, 4, 6)  # candidate beats per bar (3/4, 4/4, 6/8)


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
    tempo, beat_frames = librosa.beat.beat_track(
        y=y, sr=sr, hop_length=HOP_LENGTH, trim=False, units="frames"
    )
    beat_frames = np.asarray(beat_frames, dtype=int)
    if beat_frames.size == 0:
        raise RuntimeError("no beats could be detected in this file")

    beat_times = librosa.frames_to_time(
        beat_frames, sr=sr, hop_length=HOP_LENGTH
    )
    tempo_value = float(np.mean(np.atleast_1d(tempo)))

    report("Finding downbeats…")
    downbeats = _find_downbeats(y, sr, beat_times)

    return BeatAnalysis(
        path=str(path),
        tempo=tempo_value,
        beat_times=tuple(float(t) for t in beat_times),
        downbeat_indices=downbeats,
        duration=duration,
    )


def _find_downbeats(
    y: np.ndarray,
    sr: int,
    beat_times: np.ndarray,
) -> frozenset[int]:
    """Pick the beat index that lines up with bar starts.

    Scores every (bar length, phase) combination against the onset-strength
    envelope sampled at each beat, using a t-like statistic so short phases
    are not favoured just for having fewer samples.
    """
    count = len(beat_times)
    if count < 8:
        return frozenset()

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)
    beat_frame_idx = np.clip(
        librosa.time_to_frames(beat_times, sr=sr, hop_length=HOP_LENGTH),
        0,
        len(onset_env) - 1,
    )
    strengths = np.asarray(onset_env[beat_frame_idx], dtype=np.float64)

    spread = strengths.std()
    z = (strengths - strengths.mean()) / spread if spread > 0 else strengths

    best_lag, best_phase, best_score = 4, 0, float("-inf")
    for lag in BAR_LENGTHS:
        if count < lag * 2:
            continue
        for phase in range(lag):
            picks = z[phase::lag]
            if picks.size == 0:
                continue
            score = float(picks.sum() / np.sqrt(picks.size))
            if score > best_score:
                best_lag, best_phase, best_score = lag, phase, score

    return frozenset(range(best_phase, count, best_lag))
