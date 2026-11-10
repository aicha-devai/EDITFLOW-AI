import asyncio

from app.story_continuity import (
    _validate_model_graph,
    build_story_continuity_graph,
)


def test_graph_links_story_beats_to_timestamped_narration_visuals_and_shots():
    timeline = {"sequence": {"story_beats": [
        {"id": "b1", "title": "Discovery", "start_seconds": 0, "end_seconds": 5},
        {"id": "b2", "title": "Consequence", "start_seconds": 5, "end_seconds": 10},
    ]}}
    evidence = {
        "transcript_segments": [
            {"start_seconds": 1, "end_seconds": 3, "text": "The storm destroyed the village."},
        ],
        "visual_observations": [
            {"start_seconds": 2, "end_seconds": 4, "description": "A flooded village street."},
        ],
        "keyframes": [
            {"timestamp_seconds": 3, "object_key": "frames/one.jpg"},
            {"timestamp_seconds": 7, "object_key": "frames/two.jpg"},
        ],
    }
    result = asyncio.run(build_story_continuity_graph(
        timeline, evidence,
        {"segments": [
            {"id": "b1", "title": "Discovery", "start_seconds": 0, "end_seconds": 5, "intent": ""},
            {"id": "b2", "title": "Consequence", "start_seconds": 5, "end_seconds": 10, "intent": ""},
        ]},
    ))
    assert result["status"] == "completed"
    assert result["integrity"]["all_edges_have_evidence"] is True
    assert any(edge["type"] == "precedes" for edge in result["edges"])
    assert any(edge["type"] == "narrates" and edge["source"] == "transcript:0" for edge in result["edges"])
    assert any(edge["type"] == "observed_during" and edge["source"] == "visual:0" for edge in result["edges"])
    assert any(edge["type"] == "sampled_during" and edge["source"] == "shot:0" for edge in result["edges"])
    assert result["entity_extraction_status"] == "not_configured"


def test_graph_falls_back_to_declared_timeline_beats_without_story_analysis():
    result = asyncio.run(build_story_continuity_graph(
        {"sequence": {"story_beats": [
            {"id": "b1", "title": "Opening", "start_seconds": 0, "end_seconds": 4},
        ]}},
        {"transcript_segments": [], "visual_observations": [], "keyframes": []},
    ))
    assert any(node["id"] == "beat:b1" for node in result["nodes"])


def test_graph_only_accepts_causal_edges_with_exact_timestamped_transcript_quote():
    sources = {
        "transcript:0": {
            "kind": "transcript",
            "text": "The storm destroyed the village because the river overflowed.",
            "start_seconds": 1, "end_seconds": 4,
        },
        "visual:0": {
            "kind": "visual", "text": "A flooded street.",
            "start_seconds": 2, "end_seconds": 3,
        },
    }
    payload = {
        "entities": [
            {"id": "storm", "type": "event", "name": "River overflow",
             "evidence_refs": ["transcript:0"]},
            {"id": "damage", "type": "event", "name": "Village destruction",
             "evidence_refs": ["transcript:0", "visual:0"]},
        ],
        "relationships": [
            {"source_id": "storm", "target_id": "damage", "type": "causes",
             "evidence_refs": ["transcript:0"],
             "claim_quote": "because the river overflowed"},
            {"source_id": "storm", "target_id": "damage", "type": "causes",
             "evidence_refs": ["visual:0"], "claim_quote": "the river overflowed"},
        ],
    }
    nodes, edges, rejected = _validate_model_graph(payload, sources)
    assert len(nodes) == 2
    assert len(edges) == 1
    assert edges[0]["verification_status"] == "narration_claim_not_independently_verified"
    assert edges[0]["claim_quote"] == "because the river overflowed"
    assert "causal_edge_rejected_without_exact_causal_transcript_quote" in rejected


def test_graph_rejects_entities_without_timestamped_evidence():
    nodes, edges, rejected = _validate_model_graph({
        "entities": [{"id": "x", "type": "character", "name": "Unknown",
                      "evidence_refs": ["missing"]}],
        "relationships": [],
    }, {})
    assert nodes == []
    assert edges == []
    assert rejected == ["entity_missing_type_name_or_grounded_evidence"]
