import pytest

from app.perceptual_qc import _events


def test_black_and_freeze_events_are_reportable_warnings():
    stderr = (
        "[blackdetect] black_start:1.000 black_end:2.250 black_duration:1.250\n"
        "[freezedetect] freeze_start:4.000 freeze_end:7.500 freeze_duration:3.500\n"
    )
    black = _events(stderr, r"black_start:([0-9.]+)", r"black_end:([0-9.]+)",
                    "black_segment", "black")
    freeze = _events(stderr, r"freeze_start:([0-9.]+)", r"freeze_end:([0-9.]+)",
                     "frozen_scene", "freeze")
    assert black[0]["duration_seconds"] == 1.25
    assert freeze[0]["duration_seconds"] == 3.5
    assert black[0]["severity"] == freeze[0]["severity"] == "warning"


def test_unclosed_detection_event_keeps_start_time():
    items = _events("silence_start:3.250", r"silence_start:([0-9.]+)",
                    r"silence_end:([0-9.]+)", "audio_silence", "silence")
    assert items[0]["start_seconds"] == 3.25
    assert items[0]["end_seconds"] is None
