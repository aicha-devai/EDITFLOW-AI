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
