from app.story_analysis import analyze_story_sequence


def test_story_analysis_aligns_transcript_visuals_and_keyframes_to_story_beats():
    timeline = {
        "sequence": {"story_beats": [
            {"id": "b1", "title": "Discovery", "start_seconds": 0, "end_seconds": 5,
             "intent": "Reveal the old photograph"},
            {"id": "b2", "title": "Consequence", "start_seconds": 5, "end_seconds": 10,
             "intent": "Explain what changed"},
        ]},
        "clips": [],
    }
    evidence = {
        "transcript_segments": [
            {"start_seconds": 1, "end_seconds": 3, "text": "They found an old photograph."},
        ],
        "visual_observations": [
            {"start_seconds": 1, "end_seconds": 4, "description": "A hand holds a faded photograph."},
            {"start_seconds": 6, "end_seconds": 9, "description": "An empty hospital corridor."},
        ],
        "keyframes": [
            {"timestamp_seconds": 2, "end_seconds": 4, "object_key": "frames/1.jpg"},
            {"timestamp_seconds": 7, "end_seconds": 9, "object_key": "frames/2.jpg"},
        ],
    }
    result = __import__("asyncio").run(analyze_story_sequence(timeline, evidence))
    assert result["status"] == "completed"
    assert len(result["segments"]) == 2
    assert result["segments"][0]["transcript_coverage"] is True
    assert result["segments"][0]["visual_coverage"] is True
    assert result["segments"][0]["keyframes"][0]["object_key"] == "frames/1.jpg"
    assert result["segments"][1]["transcript_coverage"] is False
    assert any(item["code"] == "story_beat_without_transcript" for item in result["findings"])


def test_story_analysis_flags_adjacent_beat_gap_and_possible_repeated_narration():
    timeline = {
        "sequence": {"story_beats": [
            {"id": "b1", "title": "First", "start_seconds": 0, "end_seconds": 4},
            {"id": "b2", "title": "Second", "start_seconds": 7, "end_seconds": 11},
        ]},
        "clips": [],
    }
    evidence = {
        "transcript_segments": [
            {"start_seconds": 1, "end_seconds": 3, "text": "The hidden evidence reveals the same mystery again"},
            {"start_seconds": 8, "end_seconds": 10, "text": "The hidden evidence reveals the same mystery again"},
        ],
        "visual_observations": [],
        "keyframes": [],
    }
    result = __import__("asyncio").run(analyze_story_sequence(timeline, evidence))
    codes = {item["code"] for item in result["findings"]}
    assert "story_timeline_gap" in codes
    assert "possible_repeated_narration" in codes


def test_story_analysis_uses_clip_ranges_when_explicit_beat_ranges_are_missing():
    timeline = {
        "sequence": {"story_beats": [{"id": "b1", "title": "Beat without timing"}]},
        "clips": [
            {"id": "clip-1", "timeline_start": 2, "source_in": 0, "source_out": 3,
             "rationale": "Establish the location"},
        ],
    }
    result = __import__("asyncio").run(analyze_story_sequence(timeline, {
        "transcript_segments": [], "visual_observations": [], "keyframes": [],
    }))
    assert result["segments"][0]["id"] == "clip-1"
    assert result["segments"][0]["start_seconds"] == 2
    assert result["segments"][0]["end_seconds"] == 5


def test_story_analysis_does_not_claim_semantic_review_without_provider():
    import asyncio
    result = asyncio.run(analyze_story_sequence(
        {"sequence": {"story_beats": [
            {"id": "b1", "title": "Beat", "start_seconds": 0, "end_seconds": 2},
        ]}},
        {"transcript_segments": [], "visual_observations": [], "keyframes": []},
    ))
    assert result["analysis_status"] == "not_configured"
    assert result["semantic_findings"] == []
    assert result["limitations"]


def test_story_analysis_detects_near_duplicate_shots_from_frame_fingerprints():
    import asyncio
    timeline = {
        "sequence": {"story_beats": [
            {"id": "b1", "title": "Opening", "start_seconds": 0, "end_seconds": 3},
            {"id": "b2", "title": "Later", "start_seconds": 4, "end_seconds": 8},
        ]},
        "clips": [],
    }
    evidence = {
        "transcript_segments": [],
        "visual_observations": [],
        "keyframes": [
            {"timestamp_seconds": 1, "end_seconds": 2, "object_key": "frame/a.jpg",
             "perceptual_hash": "0000000000000000"},
            {"timestamp_seconds": 6, "end_seconds": 7, "object_key": "frame/b.jpg",
             "perceptual_hash": "0000000000000001"},
        ],
    }
    result = asyncio.run(analyze_story_sequence(timeline, evidence))
    duplicate = next(item for item in result["findings"] if item["code"] == "possible_duplicate_shot")
    assert duplicate["hamming_distance"] == 1
    assert duplicate["evidence_refs"][0]["object_key"] == "frame/a.jpg"
    assert duplicate["evidence_refs"][1]["object_key"] == "frame/b.jpg"
