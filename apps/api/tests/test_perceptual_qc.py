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


@pytest.mark.asyncio
async def test_quality_analysis_reports_black_freeze_silence_and_clipping(monkeypatch):
    import app.perceptual_qc as qc

    class FakeProcess:
        returncode = 0
        async def communicate(self):
            return b"", (
                "black_start:0.500 black_end:1.500 black_duration:1.000\\n"
                "freeze_start:3.000 freeze_end:6.000 freeze_duration:3.000\\n"
                "silence_start:7.000 silence_end:8.500 silence_duration:1.500\\n"
                "Peak level dB: -0.05\\nNumber of clipped samples: 4\\n"
            ).encode()

    captured = {}
    async def fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        return FakeProcess()

    monkeypatch.setattr(qc.asyncio, "create_subprocess_exec", fake_exec)
    report = await qc.analyze_render_quality("sample.mp4", includes_audio=True)

    codes = {item["code"] for item in report["findings"]}
    assert {"black_segment", "frozen_scene", "audio_silence",
            "audio_clipping", "audio_peak_near_full_scale"} <= codes
    assert report["status"] == "warnings"
    assert report["summary"]["warning_count"] == 5
    assert "blackdetect" in " ".join(captured["argv"])
    assert "freezedetect" in " ".join(captured["argv"])
    assert "silencedetect" in " ".join(captured["argv"])
    assert "astats" in " ".join(captured["argv"])


@pytest.mark.asyncio
async def test_quality_analysis_skips_audio_filters_when_timeline_has_no_audio(monkeypatch):
    import app.perceptual_qc as qc

    class FakeProcess:
        returncode = 0
        async def communicate(self):
            return b"", b""

    captured = {}
    async def fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        return FakeProcess()

    monkeypatch.setattr(qc.asyncio, "create_subprocess_exec", fake_exec)
    report = await qc.analyze_render_quality("silent.mp4", includes_audio=False)
    command = " ".join(captured["argv"])
    assert "blackdetect" in command and "freezedetect" in command
    assert "silencedetect" not in command and "astats" not in command
    assert report["analysis"]["audio_analyzed"] is False
    assert report["status"] == "passed"


@pytest.mark.asyncio
async def test_intent_annotations_downgrade_only_matching_overlapping_findings(monkeypatch):
    import app.perceptual_qc as qc

    class FakeProcess:
        returncode = 0
        async def communicate(self):
            return b"", (
                "black_start:1.000 black_end:2.000 black_duration:1.000\\n"
                "freeze_start:4.000 freeze_end:7.000 freeze_duration:3.000\\n"
                "silence_start:8.000 silence_end:9.500 silence_duration:1.500\\n"
            ).encode()

    async def fake_exec(*argv, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(qc.asyncio, "create_subprocess_exec", fake_exec)
    report = await qc.analyze_render_quality(
        "story.mp4",
        includes_audio=True,
        intent_annotations=[
            {"kind": "black_segment", "start_seconds": 0.8, "end_seconds": 2.2,
             "reason": "Intentional dramatic blackout"},
            {"kind": "audio_silence", "start_seconds": 20, "end_seconds": 22,
             "reason": "Silence belongs to a later scene"},
        ],
    )

    black = next(item for item in report["findings"] if item["code"] == "black_segment")
    freeze = next(item for item in report["findings"] if item["code"] == "frozen_scene")
    silence = next(item for item in report["findings"] if item["code"] == "audio_silence")
    assert black["severity"] == "info"
    assert black["intentional"] is True
    assert black["intent_reason"] == "Intentional dramatic blackout"
    assert freeze["severity"] == "warning"
    assert "intentional" not in freeze
    assert silence["severity"] == "warning"
    assert report["status"] == "warnings"
    assert report["summary"]["warning_count"] == 2
    assert report["summary"]["intentional_findings"] == 1


def test_timeline_qc_intent_requires_valid_non_empty_time_range():
    from pydantic import ValidationError
    from app.schemas import QCIntentRange

    valid = QCIntentRange(
        kind="frozen_scene", start_seconds=2, end_seconds=5,
        reason="Intentional dramatic hold",
    )
    assert valid.end_seconds > valid.start_seconds
    with pytest.raises(ValidationError):
        QCIntentRange(
            kind="frozen_scene", start_seconds=5, end_seconds=2,
            reason="Invalid interval",
        )
