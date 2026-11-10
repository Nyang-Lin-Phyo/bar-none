"""Structural tests for the EDL writer against the reference export.

Run with either:
    python tests/test_edl_format.py
    python -m unittest discover tests
"""

from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from edl import (  # noqa: E402
    BAR_COLOR,
    BEAT_COLOR,
    MODE_ALL,
    MODE_BOTH,
    MODE_DOWNBEATS,
    Marker,
    build_edl,
    make_markers,
)
from timecode import (  # noqa: E402
    FRAME_RATES,
    frames_to_timecode,
    get_frame_rate,
    parse_timecode,
    seconds_to_frames,
)

SAMPLE_PATH = os.path.join(ROOT, "edlFiles", "Timeline 1.edl")

MARKER_RE = re.compile(
    r"^(?P<comment>.*) \|C:(?P<color>\S+) \|M:(?P<name>.*) \|D:(?P<duration>\d+)$"
)


def read_sample() -> tuple[str, list[tuple[str, str]]]:
    """Return the sample as (text, [(event_line, marker_line), ...])."""
    with open(SAMPLE_PATH, "rb") as handle:
        text = handle.read().decode("utf-8")
    lines = text.split("\r\n")
    # Header: TITLE, FCM, blank — then event/marker pairs, each followed by blank.
    assert lines[0].startswith("TITLE: ")
    assert lines[1] == "FCM: NON-DROP FRAME"
    assert lines[2] == ""
    body = lines[3:]
    pairs = []
    i = 0
    while i < len(body) - 1 and body[i]:
        pairs.append((body[i], body[i + 1]))
        i += 2
        assert i < len(body) and body[i] == "", "expected blank line between events"
        i += 1
    return text, pairs


def split_event(line: str) -> dict[str, str]:
    """Slice an event line at the fixed column positions of the reference format."""
    assert len(line) == 78, f"event line is {len(line)} chars, expected 78"
    assert line[3:5] == "  ", "columns 4-5 must be two spaces"
    assert line[8:14].strip() == "", "columns 9-14 must be the reel field + padding"
    assert line[14] == "V", "track column"
    assert line[15:20].strip() == "", "padding after track"
    assert line[20] == "C", "transition column"
    assert line[21:29].strip() == "", "padding after transition"
    assert line[76:78] == "  ", "two trailing spaces"
    timecodes = line[29:76].split()
    assert len(timecodes) == 4, timecodes
    return {
        "event": line[0:3],
        "reel": line[5:8],
        "timecodes": " ".join(timecodes),
    }


class TimecodeTests(unittest.TestCase):
    def test_reference_timecodes_parse(self) -> None:
        rate = get_frame_rate("24")
        self.assertEqual(parse_timecode("01:00:00:00", rate), 86400)
        self.assertEqual(parse_timecode("01:00:29:03", rate), 87099)
        self.assertEqual(
            frames_to_timecode(87099, rate), "01:00:29:03"
        )

    def test_roundtrip_all_rates(self) -> None:
        for rate in FRAME_RATES:
            for frames in (0, 1, rate.nominal - 1, rate.nominal, 87099, 1234567):
                tc = frames_to_timecode(frames, rate)
                self.assertEqual(parse_timecode(tc, rate), frames, rate.label)

    def test_non_drop_seconds_roll_at_nominal(self) -> None:
        rate_23976 = get_frame_rate("23.976")
        # 23.976 fps: real second is not a timecode second, but the frame
        # counter still rolls at 24 frames per timecode second.
        self.assertEqual(seconds_to_frames(1.0, rate_23976), 24)
        self.assertEqual(frames_to_timecode(24, rate_23976), "00:00:01:00")
        rate_2997 = get_frame_rate("29.97")
        self.assertEqual(frames_to_timecode(30, rate_2997), "00:00:01:00")

    def test_bad_timecodes_rejected(self) -> None:
        rate = get_frame_rate("24")
        with self.assertRaises(ValueError):
            parse_timecode("01:00:00", rate)
        with self.assertRaises(ValueError):
            parse_timecode("01:00:00:24", rate)  # frame out of range at 24fps
        with self.assertRaises(ValueError):
            parse_timecode("01:60:00:00", rate)
        with self.assertRaises(ValueError):
            parse_timecode("aa:bb:cc:dd", rate)


class EdlStructureTests(unittest.TestCase):
    def test_sample_parses(self) -> None:
        _, pairs = read_sample()
        self.assertEqual(len(pairs), 6)
        first_event = split_event(pairs[0][0])
        self.assertEqual(first_event["event"], "001")
        self.assertEqual(first_event["reel"], "001")
        self.assertEqual(
            first_event["timecodes"],
            "01:00:29:03 01:00:29:04 01:00:29:03 01:00:29:04",
        )
        match = MARKER_RE.match(pairs[1][1])
        assert match is not None
        self.assertEqual(match["comment"], "faaawwgg")
        self.assertEqual(match["color"], "ResolveColorPurple")
        self.assertEqual(match["name"], "fewafeawf")

    def test_single_event_matches_reference_line(self) -> None:
        """One marker at 29.125 s reproduces the sample's first event exactly."""
        rate = get_frame_rate("24")
        # Beat times are relative to the clip's start (01:00:00:00 = 0 s).
        marker = Marker(29.125, "Marker 4", "ResolveColorBlue")
        text = build_edl(
            "Timeline 1", [marker], rate, "01:00:00:00", "01:00:00:00"
        )
        lines = text.split("\r\n")
        sample_text, sample_pairs = read_sample()
        self.assertEqual(lines[3], sample_pairs[0][0])
        self.assertEqual(lines[4], sample_pairs[0][1])
        self.assertEqual(lines[0], sample_text.split("\r\n")[0])
        self.assertEqual(lines[1], "FCM: NON-DROP FRAME")

    def test_regenerate_reference_byte_identical(self) -> None:
        """Parse the reference EDL and rebuild it from its own timecodes."""
        sample_text, pairs = read_sample()
        rate = get_frame_rate("24")
        title = sample_text.split("\r\n")[0][len("TITLE: "):]

        markers = []
        for event_line, marker_line in pairs:
            event = split_event(event_line)
            source_in, _, record_in, _ = event["timecodes"].split()
            assert source_in == record_in, "reference clip sits at 01:00:00:00"
            clip_start = parse_timecode("01:00:00:00", rate)
            seconds = (parse_timecode(source_in, rate) - clip_start) / rate.fps
            match = MARKER_RE.match(marker_line)
            assert match is not None
            markers.append(
                Marker(
                    time_seconds=seconds,
                    name=match["name"],
                    color=match["color"],
                    comment=match["comment"],
                )
            )

        rebuilt = build_edl(
            title, markers, rate, "01:00:00:00", "01:00:00:00"
        )
        self.assertEqual(rebuilt, sample_text)

    def test_timeline_offset_shifts_record_only(self) -> None:
        rate = get_frame_rate("24")
        marker = Marker(1.0, "Beat 1", BEAT_COLOR)
        text = build_edl(
            "T", [marker], rate, "01:00:00:00", "01:10:00:00"
        )
        event_line = text.split("\r\n")[3]
        event = split_event(event_line)
        source_in, _, record_in, _ = event["timecodes"].split()
        self.assertEqual(source_in, "01:00:01:00")
        self.assertEqual(record_in, "01:10:01:00")

    def test_duplicate_frames_merge(self) -> None:
        rate = get_frame_rate("24")
        markers = [Marker(0.0, "Beat 1"), Marker(0.001, "Beat 2"), Marker(0.5, "Beat 3")]
        text = build_edl("T", markers, rate, "01:00:00:00", "01:00:00:00")
        events = [
            line for line in text.split("\r\n") if re.match(r"^\d{3}  ", line)
        ]
        self.assertEqual(len(events), 2)
        self.assertTrue(events[0].startswith("001"))
        self.assertTrue(events[1].startswith("002"))

    def test_sanitizes_pipe_and_newline(self) -> None:
        rate = get_frame_rate("24")
        marker = Marker(0.0, "Bad|Name\nHere", BEAT_COLOR, comment="c\nl")
        text = build_edl("T\nitle", [marker], rate, "01:00:00:00", "01:00:00:00")
        lines = text.split("\r\n")
        self.assertEqual(lines[0], "TITLE: T itle")
        self.assertNotIn("\n", lines[4])
        self.assertNotIn("|C", lines[4].split("|C")[0])  # comment has no pipe breaks
        self.assertIn("|M:Bad/Name Here |D:1", lines[4])


class MarkerModeTests(unittest.TestCase):
    BEATS = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
    DOWNBEATS = frozenset({0, 4})

    def test_all_beats(self) -> None:
        markers = make_markers(self.BEATS, self.DOWNBEATS, MODE_ALL)
        self.assertEqual(len(markers), 8)
        self.assertEqual(markers[0].name, "Beat 1")
        self.assertEqual(markers[7].name, "Beat 8")
        self.assertTrue(all(m.color == BEAT_COLOR for m in markers))

    def test_downbeats_only(self) -> None:
        markers = make_markers(self.BEATS, self.DOWNBEATS, MODE_DOWNBEATS)
        self.assertEqual([m.name for m in markers], ["Bar 1", "Bar 2"])
        self.assertTrue(all(m.color == BAR_COLOR for m in markers))
        self.assertEqual(markers[0].time_seconds, 0.0)
        self.assertEqual(markers[1].time_seconds, 2.0)

    def test_both_color_coded(self) -> None:
        markers = make_markers(self.BEATS, self.DOWNBEATS, MODE_BOTH)
        self.assertEqual(len(markers), 8)
        self.assertEqual(markers[0].name, "Bar 1")
        self.assertEqual(markers[0].color, BAR_COLOR)
        self.assertEqual(markers[1].name, "Beat 2")
        self.assertEqual(markers[1].color, BEAT_COLOR)
        self.assertEqual(markers[4].name, "Bar 2")
        self.assertEqual(markers[4].color, BAR_COLOR)

    def test_unknown_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_markers(self.BEATS, self.DOWNBEATS, "everything")


if __name__ == "__main__":
    unittest.main(verbosity=2)
