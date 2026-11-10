"""SMPTE timecode helpers (non-drop frame, matching DaVinci Resolve EDL export)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrameRate:
    """A timeline frame rate.

    ``fps`` is real frames per second (23.976 for the label "23.976").
    ``nominal`` is how many frames make one timecode second in non-drop
    counting (24 for "23.976", 30 for "29.97", ...).
    """

    label: str
    fps: float
    nominal: int


FRAME_RATES: tuple[FrameRate, ...] = (
    FrameRate("23.976", 24000 / 1001, 24),
    FrameRate("24", 24.0, 24),
    FrameRate("25", 25.0, 25),
    FrameRate("29.97", 30000 / 1001, 30),
    FrameRate("30", 30.0, 30),
    FrameRate("50", 50.0, 50),
    FrameRate("59.94", 60000 / 1001, 60),
    FrameRate("60", 60.0, 60),
)

DEFAULT_FRAME_RATE_LABEL = "24"
DEFAULT_CLIP_SOURCE_TC = "01:00:00:00"
DEFAULT_TIMELINE_START_TC = "01:00:00:00"


def get_frame_rate(label: str) -> FrameRate:
    """Look up a frame rate by its label, e.g. ``"24"`` or ``"23.976"``."""
    for rate in FRAME_RATES:
        if rate.label == label:
            return rate
    raise ValueError(f"unknown frame rate: {label!r}")


def seconds_to_frames(seconds: float, rate: FrameRate) -> int:
    """Convert a position in seconds to a frame number on this timeline."""
    return int(round(seconds * rate.fps))


def frames_to_seconds(frames: int, rate: FrameRate) -> float:
    return frames / rate.fps


def frames_to_timecode(frames: int, rate: FrameRate) -> str:
    """Format a frame number as non-drop ``HH:MM:SS:FF``."""
    if frames < 0:
        raise ValueError("frame number is negative")
    ff = frames % rate.nominal
    total_seconds = frames // rate.nominal
    ss = total_seconds % 60
    mm = (total_seconds // 60) % 60
    hh = total_seconds // 3600
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def parse_timecode(timecode: str, rate: FrameRate) -> int:
    """Parse ``HH:MM:SS:FF`` into a frame number for this frame rate."""
    parts = timecode.strip().split(":")
    try:
        if len(parts) != 4:
            raise ValueError
        hh, mm, ss, ff = (int(part) for part in parts)
    except ValueError:
        raise ValueError(
            f"bad timecode {timecode!r} — expected HH:MM:SS:FF"
        ) from None
    if hh < 0 or not (0 <= mm < 60 and 0 <= ss < 60 and 0 <= ff < rate.nominal):
        raise ValueError(
            f"timecode {timecode!r} is out of range for {rate.label} fps "
            f"(frames run 0..{rate.nominal - 1})"
        )
    return ((hh * 60 + mm) * 60 + ss) * rate.nominal + ff
