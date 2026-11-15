import struct

import pytest

from app.render_engine import RenderPlanError, build_ffmpeg_plan


def _timeline():
    return {
        "sequence": {"width": 1080, "height": 1920, "fps": 30},
        "clips": [
            {
                "id": "clip-a",
                "asset_id": "asset-a",
                "timeline_start": 0,
                "source_in": 1,
                "source_out": 4,
                "audio_gain_db": -3,
            },
            {
                "id": "clip-b",
                "asset_id": "asset-b",
                "timeline_start": 3,
                "source_in": 0,
                "source_out": 2,
                "audio_gain_db": 0,
            },
        ],
    }


def test_ffmpeg_plan_uses_resolved_paths_and_pinned_timeline_order():
    plan = build_ffmpeg_plan(
        _timeline(),
        {"asset-a": "/media/a.mp4", "asset-b": "/media/b.mp4"},
        "/renders/final.mp4",
        asset_has_audio={"asset-a": True, "asset-b": False},
    )

    assert plan.duration_seconds == 5
    assert plan.input_asset_ids == ("asset-a", "asset-b")
    assert plan.includes_audio is True
    assert plan.argv.count("-i") == 2
    assert plan.argv.count("-protocol_whitelist") == 2
    assert plan.argv.count("-format_whitelist") == 2
    assert plan.argv.count("-codec_whitelist") == 2
    assert "/media/a.mp4" in plan.argv
    assert "/media/b.mp4" in plan.argv
    assert "[vout]" in plan.argv
    assert "[aout]" in plan.argv
    assert plan.argv[-1] == "/renders/final.mp4"
    assert "between(t,0.0,3.0)" in plan.argv[plan.argv.index("-filter_complex") + 1]


def test_ffmpeg_plan_can_render_silent_source_media():
    plan = build_ffmpeg_plan(
        _timeline(),
        {"asset-a": "/media/a.mp4", "asset-b": "/media/b.mp4"},
        "/renders/silent.mp4",
    )
    assert plan.includes_audio is False
    assert "-an" in plan.argv


def test_ffmpeg_plan_rejects_missing_asset_resolution():
    with pytest.raises(RenderPlanError, match="No resolved media path"):
        build_ffmpeg_plan(_timeline(), {"asset-a": "/media/a.mp4"}, "/renders/out.mp4")


def test_ffmpeg_plan_rejects_unsupported_custom_transform():
    timeline = _timeline()
    timeline["clips"][0]["transform"] = {"scale": 1.2}
    with pytest.raises(RenderPlanError, match="Custom clip transforms"):
        build_ffmpeg_plan(
            timeline,
            {"asset-a": "/media/a.mp4", "asset-b": "/media/b.mp4"},
            "/renders/out.mp4",
        )


@pytest.mark.parametrize("width,height", [(1081, 1920), (0, 1920), (8000, 1920)])
def test_ffmpeg_plan_rejects_invalid_output_dimensions(width, height):
    with pytest.raises(RenderPlanError):
        build_ffmpeg_plan(
            _timeline(),
            {"asset-a": "/media/a.mp4", "asset-b": "/media/b.mp4"},
            "/renders/out.mp4",
            {"width": width, "height": height},
        )


def test_ffmpeg_plan_rejects_drm_pssh_source_as_a_validation_error(tmp_path):
    source = tmp_path / "protected.mp4"

    def box(kind: bytes, payload: bytes = b"") -> bytes:
        return struct.pack(">I4s", 8 + len(payload), kind) + payload

    source.write_bytes(
        box(b"ftyp", b"isom0000")
        + box(b"moov", box(b"pssh", b"\x00\x00\x00\x00"))
    )
    with pytest.raises(RenderPlanError, match="PSSH atoms are not supported"):
        build_ffmpeg_plan(
            _timeline(),
            {"asset-a": str(source), "asset-b": "/media/b.mp4"},
            "/renders/out.mp4",
        )
