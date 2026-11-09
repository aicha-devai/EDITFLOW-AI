import pytest

from app.media_probe import MediaInfo
from app.output_integrity import OutputIntegrityError, validate_render_output
from app.render_engine import RenderPlan


def _plan():
    return RenderPlan(
        argv=("ffmpeg",), output_path="/tmp/out.mp4", duration_seconds=2.0,
        input_asset_ids=("asset",), includes_audio=True, width=360, height=640, fps=30,
    )


def _info(**changes):
    values = dict(
        duration_seconds=2.0, has_video=True, has_audio=True, width=360, height=640,
        video_codec="h264", audio_codec="aac", format_name="mov,mp4,m4a,3gp,3g2,mj2",
    )
    values.update(changes)
    return MediaInfo(**values)


def test_output_integrity_accepts_matching_mp4(tmp_path):
    path = tmp_path / "out.mp4"
    path.write_bytes(b"valid-output")
    validate_render_output(path, _plan(), _info())


@pytest.mark.parametrize(("changes", "message"), [
    ({"format_name": "matroska,webm"}, "not a valid MP4"),
    ({"has_video": False, "video_codec": None}, "no decodable video"),
    ({"video_codec": "mpeg4"}, "Unexpected video codec"),
    ({"width": 720}, "width mismatch"),
    ({"height": 1280}, "height mismatch"),
    ({"has_audio": False, "audio_codec": None}, "audio presence mismatch"),
    ({"audio_codec": "mp3"}, "Unexpected audio codec"),
    ({"duration_seconds": 3.0}, "duration mismatch"),
])
def test_output_integrity_rejects_mismatched_output(tmp_path, changes, message):
    path = tmp_path / "out.mp4"
    path.write_bytes(b"not-empty")
    with pytest.raises(OutputIntegrityError, match=message):
        validate_render_output(path, _plan(), _info(**changes))


def test_output_integrity_rejects_empty_file(tmp_path):
    path = tmp_path / "out.mp4"
    path.write_bytes(b"")
    with pytest.raises(OutputIntegrityError, match="empty"):
        validate_render_output(path, _plan(), _info())
