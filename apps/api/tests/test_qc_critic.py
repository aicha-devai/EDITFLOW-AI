import pytest

from app.qc_critic import generate_qc_critic_proposals


def test_critic_suggests_intent_only_when_timeline_context_supports_it():
    report = {"findings": [
        {"code": "black_segment", "start_seconds": 4, "end_seconds": 5},
        {"code": "audio_silence", "start_seconds": 9, "end_seconds": 11},
    ]}
    timeline = {
        "editorial_notes": ["Keep a dramatic pause before the final reveal."],
        "clips": [{
            "timeline_start": 3, "source_in": 0, "source_out": 3,
            "rationale": "Cut to black before the reveal.",
        }],
    }
    result = generate_qc_critic_proposals(report, timeline)
    black, silence = result["proposals"]
    assert black["recommendation"] == "mark_intentional"
    assert black["confidence"] == 0.86
    assert "cut to black" in black["matched_cues"]
    assert silence["recommendation"] == "mark_intentional"
    assert silence["confidence"] == 0.72
    assert result["automatic_changes"] == 0
    assert black["requires_user_approval"] is True


def test_critic_does_not_assume_unexplained_anomalies_are_intentional():
    result = generate_qc_critic_proposals(
        {"findings": [{"code": "frozen_scene", "start_seconds": 2, "end_seconds": 6}]},
        {"editorial_notes": ["Fast-paced documentary edit"], "clips": []},
    )
    proposal = result["proposals"][0]
    assert proposal["recommendation"] == "inspect_as_potential_issue"
    assert proposal["confidence"] == 0.48
    assert proposal["matched_cues"] == []


def test_critic_ignores_measurement_only_findings_and_open_intervals():
    result = generate_qc_critic_proposals(
        {"findings": [
            {"code": "audio_clipping", "peak_dbfs": 0},
            {"code": "black_segment", "start_seconds": 2, "end_seconds": None},
        ]},
        {},
    )
    assert result["proposals"] == []


def test_critic_proposal_ids_are_stable_and_range_specific():
    report = {"findings": [{"code": "black_segment", "start_seconds": 1, "end_seconds": 2}]}
    first = generate_qc_critic_proposals(report, {})["proposals"][0]["proposal_id"]
    second = generate_qc_critic_proposals(report, {})["proposals"][0]["proposal_id"]
    assert first == second


@pytest.mark.asyncio
async def test_critic_approval_appends_new_timeline_version_and_rejects_inspect_only(db_session):
    from app.models import Project, RenderJob
    from app.schemas import TimelineDocument
    from app.versioning import save_timeline
    from app.qc_critic import approve_qc_intent_proposals, StaleQCCriticBase

    project = Project(title="QC critic approval")
    db_session.add(project)
    await db_session.flush()
    doc = TimelineDocument(
        project_id=project.id,
        editorial_notes=["Intentional blackout before the reveal"],
    )
    version, _ = await save_timeline(db_session, project.id, doc, 0)
    job = RenderJob(
        project_id=project.id,
        timeline_version_id=version.id,
        timeline_snapshot={**doc.model_dump(mode="json"), "version": 1},
        timeline_hash=version.content_hash,
        status="succeeded",
        render_profile={},
        quality_report={"findings": [
            {"code": "black_segment", "start_seconds": 2, "end_seconds": 3},
            {"code": "frozen_scene", "start_seconds": 5, "end_seconds": 9},
        ]},
    )
    db_session.add(job)
    await db_session.flush()
    suggestions = generate_qc_critic_proposals(job.quality_report, job.timeline_snapshot)["proposals"]
    black = next(item for item in suggestions if item["kind"] == "black_segment")
    frozen = next(item for item in suggestions if item["kind"] == "frozen_scene")

    with pytest.raises(ValueError):
        await approve_qc_intent_proposals(
            db_session, project.id, job.id, [frozen["proposal_id"]], 1
        )
    row, created, count = await approve_qc_intent_proposals(
        db_session, project.id, job.id, [black["proposal_id"]], 1
    )
    assert created is True
    assert row.version == 2
    assert count == 1
    assert row.timeline_json["qc_intent"][0]["kind"] == "black_segment"

    with pytest.raises(StaleQCCriticBase):
        await approve_qc_intent_proposals(
            db_session, project.id, job.id, [black["proposal_id"]], 1
        )


@pytest.mark.asyncio
async def test_critic_refuses_approval_when_project_head_moved_past_render(db_session):
    from app.models import Project, RenderJob
    from app.schemas import TimelineDocument
    from app.versioning import save_timeline
    from app.qc_critic import approve_qc_intent_proposals, StaleQCCriticBase

    project = Project(title="Stale QC critic")
    db_session.add(project)
    await db_session.flush()
    first, _ = await save_timeline(db_session, project.id, TimelineDocument(project_id=project.id), 0)
    job = RenderJob(
        project_id=project.id, timeline_version_id=first.id,
        timeline_snapshot={"project_id": str(project.id), "sequence": {}, "clips": [],
                           "editorial_notes": [], "version": 1, "schema_version": "0.1"},
        timeline_hash=first.content_hash, status="succeeded", render_profile={},
        quality_report={"findings": [{"code": "black_segment", "start_seconds": 1, "end_seconds": 2}]},
    )
    db_session.add(job)
    await db_session.flush()
    await save_timeline(
        db_session, project.id,
        TimelineDocument(project_id=project.id, sequence={"changed": True}), 1,
    )
    with pytest.raises(StaleQCCriticBase):
        await approve_qc_intent_proposals(db_session, project.id, job.id, ["not-used"], 2)


def test_critic_skips_findings_already_classified_as_intentional():
    result = generate_qc_critic_proposals(
        {"findings": [{
            "code": "black_segment", "severity": "info", "intentional": True,
            "start_seconds": 2, "end_seconds": 3,
        }]},
        {"editorial_notes": ["Intentional blackout"]},
    )
    assert result["proposals"] == []
    assert result["automatic_changes"] == 0



def test_generic_reveal_note_does_not_mark_black_segment_intentional():
    result = generate_qc_critic_proposals(
        {"findings": [{"code": "black_segment", "start_seconds": 3, "end_seconds": 5}]},
        {"editorial_notes": ["Build suspense for the reveal"], "clips": []},
    )
    proposal = result["proposals"][0]
    assert proposal["recommendation"] == "inspect_as_potential_issue"
    assert proposal["matched_cues"] == []


def test_confidence_is_explicitly_labeled_as_heuristic_not_probability():
    result = generate_qc_critic_proposals(
        {"findings": [{"code": "black_segment", "start_seconds": 3, "end_seconds": 5}]},
        {"editorial_notes": ["Intentional fade to black before the reveal"], "clips": []},
    )
    proposal = result["proposals"][0]
    assert proposal["recommendation"] == "mark_intentional"
    assert proposal["confidence_type"] == "heuristic_score_not_probability"



def test_critic_attaches_timestamped_multimodal_evidence_and_story_beat_context():
    result = generate_qc_critic_proposals(
        {
            "findings": [{"code": "frozen_scene", "start_seconds": 4, "end_seconds": 7}],
            "evidence": {
                "transcript_segments": [
                    {"start_seconds": 3, "end_seconds": 5, "text": "Look closely at the photograph."},
                    {"start_seconds": 8, "end_seconds": 9, "text": "Outside the event window."},
                ],
                "visual_observations": [
                    {"start_seconds": 5, "end_seconds": 6, "description": "A still evidence-board frame."},
                ],
                "audio_observations": [
                    {"start_seconds": 4, "end_seconds": 7, "description": "Narration continues clearly."},
                ],
            },
        },
        {
            "sequence": {
                "story_beats": [{"id": "beat-1", "title": "Evidence reveal"}],
            },
            "clips": [{
                "timeline_start": 3, "source_in": 0, "source_out": 5,
                "story_beat_id": "beat-1",
            }],
        },
    )
    evidence = result["proposals"][0]["temporal_evidence"]
    assert evidence["available_modalities"] == ["audio", "transcript", "visual"]
    assert len(evidence["transcript_segments"]) == 1
    assert evidence["observations"][0]["modality"] == "visual"
    assert {item["modality"] for item in evidence["observations"]} == {"audio", "visual"}
    assert evidence["story_beats"] == [{"id": "beat-1", "title": "Evidence reveal"}]


def test_critic_does_not_claim_multimodal_evidence_when_none_was_supplied():
    result = generate_qc_critic_proposals(
        {"findings": [{"code": "black_segment", "start_seconds": 1, "end_seconds": 2}]},
        {},
    )
    evidence = result["proposals"][0]["temporal_evidence"]
    assert evidence == {
        "transcript_segments": [],
        "keyframes": [],
        "observations": [],
        "story_beats": [],
        "extraction_status": "not_available",
        "transcription_status": "not_available",
        "transcription_provider": None,
        "visual_semantics_status": "not_available",
        "audio_artifact": None,
        "available_modalities": [],
    }


def test_qc_critic_exposes_story_sequence_review_without_auto_changes():
    result = generate_qc_critic_proposals(
        {"findings": [], "story_analysis": {
            "status": "completed", "analysis_status": "completed",
            "analysis_model": "test-model",
            "findings": [{
                "code": "possible_narration_visual_mismatch",
                "start_seconds": 4, "end_seconds": 7,
                "summary": "Narration describes a photograph while the visual evidence shows a corridor.",
                "evidence_refs": ["b2", "transcript:4.2-5.1", "visual:5.0-6.0"],
            }],
        }},
        {},
    )
    review = result["story_review"]
    assert review["analysis_status"] == "completed"
    assert review["analysis_model"] == "test-model"
    assert review["findings"][0]["code"] == "possible_narration_visual_mismatch"
    assert review["requires_human_review"] is True
    assert review["automatic_changes"] == 0
    assert result["automatic_changes"] == 0
