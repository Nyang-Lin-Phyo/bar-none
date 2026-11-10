"""CMX3600-style EDL writer in the DaVinci Resolve flavour.

The output mirrors the reference export ``edlFiles/Timeline 1.edl`` byte for
byte: CRLF line endings, a comment field on the marker line, and two trailing
spaces on event lines.

Structure, per marker::

    001  001      V     C        <src in> <src in+1f> <rec in> <rec in+1f>
     |C:ResolveColorBlue |M:Beat 1 |D:1
    <blank line>
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from timecode import (
    FrameRate,
    frames_to_timecode,
    parse_timecode,
    seconds_to_frames,
)

REEL = "001"
TRACK = "V"
EVENT_TYPE = "C"  # C = cut

# Resolve marker colours (Resolve's own EDL colour names).
BEAT_COLOR = "ResolveColorBlue"
BAR_COLOR = "ResolveColorRed"

MODE_ALL = "all"
MODE_DOWNBEATS = "downbeats"
MODE_BOTH = "both"


@dataclass(frozen=True)
class Marker:
    """One beat that becomes a 1-frame marker event in Resolve."""

    time_seconds: float
    name: str
    color: str = BEAT_COLOR
    comment: str = ""


def make_markers(
    beat_times: Sequence[float],
    downbeat_indices: Iterable[int],
    mode: str,
) -> list[Marker]:
    """Turn detected beats into named, colour-coded markers.

    ``downbeat_indices`` are 0-based positions into ``beat_times``.
    Marker names: ``Beat 1..N`` for beats, ``Bar 1..N`` for downbeats.
    """
    downbeats = set(downbeat_indices)
    markers: list[Marker] = []
    bar = 0
    for index, time_seconds in enumerate(beat_times):
        is_bar_start = index in downbeats
        if mode == MODE_ALL:
            markers.append(Marker(float(time_seconds), f"Beat {index + 1}", BEAT_COLOR))
        elif mode == MODE_DOWNBEATS:
            if is_bar_start:
                bar += 1
                markers.append(Marker(float(time_seconds), f"Bar {bar}", BAR_COLOR))
        elif mode == MODE_BOTH:
            if is_bar_start:
                bar += 1
                markers.append(Marker(float(time_seconds), f"Bar {bar}", BAR_COLOR))
            else:
                markers.append(
                    Marker(float(time_seconds), f"Beat {index + 1}", BEAT_COLOR)
                )
        else:
            raise ValueError(f"unknown marker mode: {mode!r}")
    return markers


def _sanitize(text: str) -> str:
    """Keep marker/comment fields on a single line and free of field breaks."""
    return " ".join(str(text).replace("|", "/").splitlines()).strip()


def build_edl(
    title: str,
    markers: Sequence[Marker],
    rate: FrameRate,
    clip_source_tc: str,
    timeline_start_tc: str,
) -> str:
    """Render markers as EDL text (CRLF line endings, non-drop frame).

    ``clip_source_tc``   — timecode of the music file's first frame; this is
                           reel ``001``'s source position in the EDL.
    ``timeline_start_tc`` — where the music sits on the destination timeline;
                           event/marker positions are relative to it.
    """
    source_start = parse_timecode(clip_source_tc, rate)
    record_start = parse_timecode(timeline_start_tc, rate)

    parts = [f"TITLE: {_sanitize(title)}\r\nFCM: NON-DROP FRAME\r\n\r\n"]
    event_number = 0
    previous_record_frame: int | None = None

    for marker in markers:
        beat_frame = seconds_to_frames(marker.time_seconds, rate)
        source_in = source_start + beat_frame
        record_in = record_start + beat_frame

        # Two beats can round onto the same frame at extreme tempos; emit one
        # event per frame so Resolve never gets overlapping 1-frame cuts.
        if record_in == previous_record_frame:
            continue
        previous_record_frame = record_in
        event_number += 1

        event_line = (
            f"{event_number:03d}  {REEL:<9}{TRACK}     {EVENT_TYPE}        "
            f"{frames_to_timecode(source_in, rate)} "
            f"{frames_to_timecode(source_in + 1, rate)} "
            f"{frames_to_timecode(record_in, rate)} "
            f"{frames_to_timecode(record_in + 1, rate)}  "
        )
        marker_line = (
            f"{_sanitize(marker.comment)} |C:{marker.color} "
            f"|M:{_sanitize(marker.name)} |D:1"
        )
        parts.append(f"{event_line}\r\n{marker_line}\r\n\r\n")

    return "".join(parts)
