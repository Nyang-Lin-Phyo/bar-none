"""Cut-point detection and punch-aware snapping tests.

Builds synthetic tracks — low kick bursts with sharper, higher hat
bursts in between — and asserts markers land on the kicks (what you'd
cut on), respect the spacing floor, and never appear in silence.

Run with either:
    python tests/test_cut_points.py
    python -m unittest discover tests
"""

from __future__ import annotations

import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from beats import _snap_to_onsets, find_cut_points  # noqa: E402
from edl import BAR_COLOR, MODE_CUT, make_markers  # noqa: E402

SR = 22050
HOP = 512


def _burst(y: np.ndarray, start: float, freq: float, amp: float, decay: float) -> None:
    n = min(int(0.2 * SR), len(y) - int(start * SR))
    if n <= 0:
        return
    i0 = int(start * SR)
    t = np.arange(n) / SR
    y[i0 : i0 + n] += amp * np.sin(2 * np.pi * freq * t) * np.exp(-decay * t)


def synth(
    kicks: list[float],
    hats: list[float],
    duration: float,
    kick_amp: float = 0.7,
    hat_amp: float = 0.5,
) -> np.ndarray:
    """Low, punchy kick bursts with sharper high hat bursts in between."""
    y = np.zeros(int(SR * duration))
    for t in kicks:
        _burst(y, t, freq=60.0, amp=kick_amp, decay=25.0)
    for t in hats:
        _burst(y, t, freq=9000.0, amp=hat_amp, decay=60.0)
    return y


def _bump(envelope: np.ndarray, t: float, amp: float) -> None:
    center = int(round(t * SR / HOP))
    for d in range(-3, 4):
        i = center + d
        if 0 <= i < len(envelope):
            envelope[i] = max(envelope[i], amp * math.exp(-(d * d) / 2.0))


class CutPointTests(unittest.TestCase):
    def test_cuts_land_on_kicks_not_hats(self) -> None:
        kicks = [0.5 + i for i in range(20)]  # 0.5 .. 19.5 s
        hats = [t + 0.5 for t in kicks]  # exactly halfway between kicks
        y = synth(kicks, hats, duration=20.5)

        cuts = find_cut_points(y, SR, min_gap=0.75)

        self.assertGreaterEqual(len(cuts), 16)
        for t in cuts:
            nearest_kick = min(abs(t - k) for k in kicks)
            nearest_hat = min(abs(t - h) for h in hats)
            self.assertLess(nearest_kick, 0.06, f"cut at {t:.2f}s missed the kick")
            self.assertGreater(nearest_hat, 0.1, f"cut at {t:.2f}s landed on a hat")

    def test_min_gap_respected(self) -> None:
        kicks = [0.5 + 0.8 * i for i in range(20)]  # tighter than the gap
        y = synth(kicks, [], duration=17.0)
        min_gap = 1.0

        cuts = find_cut_points(y, SR, min_gap=min_gap)

        self.assertGreater(len(cuts), 1)
        self.assertLess(len(cuts), len(kicks))  # spacing had to drop some
        gaps = np.diff(cuts)
        self.assertTrue(np.all(gaps >= min_gap - 1e-9), gaps)

    def test_silence_gets_no_cuts(self) -> None:
        kicks = [10.0 + i for i in range(10)]  # first 10 s are silent
        y = synth(kicks, [], duration=20.0)

        cuts = find_cut_points(y, SR, min_gap=1.0)

        self.assertGreaterEqual(len(cuts), 5)
        self.assertGreaterEqual(
            min(cuts), 9.8, "marker placed inside the silent intro"
        )

    def test_make_cut_markers(self) -> None:
        markers = make_markers((1.0, 2.5, 4.25), (), MODE_CUT)
        self.assertEqual([m.name for m in markers], ["Cut 1", "Cut 2", "Cut 3"])
        self.assertTrue(all(m.color == BAR_COLOR for m in markers))
        self.assertEqual([m.time_seconds for m in markers], [1.0, 2.5, 4.25])


class SnapTests(unittest.TestCase):
    def test_snap_prefers_punch_over_nearer_hat(self) -> None:
        """A nearer hat tick must not steal a beat from the real hit.

        Hats sit closer to each grid beat than the kicks do, but carry
        no punch (40-2500 Hz) — the snap must rank targets by punch
        flux, not distance.
        """
        duration = 6.0
        n_frames = int(duration * SR / HOP) + 1
        kicks = [1.0, 2.0, 3.0, 4.0, 5.0]
        hats = [k + 0.35 for k in kicks]  # nearer to each beat than the kick

        punch = np.zeros(n_frames)
        for t in kicks:
            _bump(punch, t, 1.0)
        for t in hats:
            _bump(punch, t, 0.05)  # hats carry no punch

        beats = np.array([k + 0.2 for k in kicks])
        rms = np.ones(n_frames)  # everything audible: no silence floor
        snapped = _snap_to_onsets(beats, punch, rms, SR)

        self.assertEqual(len(snapped), len(beats))
        for t, k in zip(snapped, kicks):
            # one frame of quantisation (~23 ms) plus the bump width
            self.assertAlmostEqual(t, k, delta=0.05, msg=f"snapped to {t:.2f}s")
            self.assertGreater(abs(t - (k + 0.35)), 0.1, "snapped onto a hat")


if __name__ == "__main__":
    unittest.main()
