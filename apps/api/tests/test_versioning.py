import uuid
import pytest
from sqlalchemy import select, func
from app.models import Asset, Project, TimelineVersion
from app.schemas import TimelineDocument
from app.versioning import save_timeline, restore_version, compare_versions, VersionConflict

@pytest.mark.asyncio
async def test_first_save_and_unchanged_timeline_is_noop(db_session):
    project = Project(title="Versioning test")
    db_session.add(project)
    await db_session.flush()
    timeline = TimelineDocument(project_id=project.id, sequence={"width": 1080}, clips=[])
    first, created = await save_timeline(db_session, project.id, timeline, expected_version=0)
    assert created is True
    assert first.version == 1

    same, created = await save_timeline(db_session, project.id, timeline, expected_version=1)
    assert created is False
    assert same.id == first.id
    count = await db_session.scalar(select(func.count()).select_from(TimelineVersion))
    assert count == 1

@pytest.mark.asyncio
async def test_restore_appends_and_preserves_later_versions(db_session):
    project = Project(title="Restore test")
    db_session.add(project)
    await db_session.flush()
    first_timeline = TimelineDocument(project_id=project.id, sequence={"fps": 24}, clips=[])
    second_timeline = TimelineDocument(project_id=project.id, sequence={"fps": 30}, clips=[])
    v1, _ = await save_timeline(db_session, project.id, first_timeline, 0)
    v2, _ = await save_timeline(db_session, project.id, second_timeline, 1)

    restored, created = await restore_version(db_session, project.id, 1, expected_version=2)
    assert created is True
    assert restored.version == 3
    assert restored.restored_from_version_id == v1.id
    assert v2.version == 2
    versions = (await db_session.scalars(
        select(TimelineVersion).where(TimelineVersion.project_id == project.id).order_by(TimelineVersion.version)
    )).all()
    assert [v.version for v in versions] == [1, 2, 3]
    assert versions[2].timeline_json["sequence"] == {"fps": 24}

@pytest.mark.asyncio
async def test_stale_write_is_rejected(db_session):
    project = Project(title="Concurrency contract")
    db_session.add(project)
    await db_session.flush()
    a = TimelineDocument(project_id=project.id, sequence={"x": 1})
    b = TimelineDocument(project_id=project.id, sequence={"x": 2})
    await save_timeline(db_session, project.id, a, 0)
    await save_timeline(db_session, project.id, b, 1)
    with pytest.raises(VersionConflict):
        await save_timeline(db_session, project.id, a, 1)

@pytest.mark.asyncio
async def test_idempotency_key_returns_existing_version(db_session):
    project = Project(title="Idempotency")
    db_session.add(project)
    await db_session.flush()
    timeline = TimelineDocument(project_id=project.id, sequence={"scene": "one"})
    first, created = await save_timeline(db_session, project.id, timeline, 0, idempotency_key="request-1")
    replay, replay_created = await save_timeline(
        db_session, project.id, timeline, expected_version=0, idempotency_key="request-1"
    )
    assert created is True
    assert replay_created is False
    assert replay.id == first.id

@pytest.mark.asyncio
async def test_compare_reports_changed_timeline_fields(db_session):
    project = Project(title="Diff")
    db_session.add(project)
    await db_session.flush()
    timeline_a = TimelineDocument(project_id=project.id, sequence={"fps": 24})
    timeline_b = TimelineDocument(project_id=project.id, sequence={"fps": 60})
    await save_timeline(db_session, project.id, timeline_a, 0)
    await save_timeline(db_session, project.id, timeline_b, 1)
    result = await compare_versions(db_session, project.id, 1, 2)
    assert result["added"] == []
    assert result["removed"] == []
    assert result["changed"] == []
    assert result["sequence_changes"] == {"fps": {"before": 24, "after": 60}}
    assert result["editorial_notes_changed"] is False


@pytest.mark.asyncio
async def test_clip_level_diff_reports_added_and_modified_clips(db_session):
    project = Project(title="Clip diff")
    db_session.add(project)
    await db_session.flush()
    asset = Asset(project_id=project.id, object_key="test/source.mp4")
    db_session.add(asset)
    await db_session.flush()
    clip_id = uuid.uuid4()
    clip_a = {
        "id": clip_id, "asset_id": asset.id, "track_id": "V1",
        "timeline_start": 0, "source_in": 0, "source_out": 4,
    }
    clip_b = {**clip_a, "timeline_start": 2}
    new_clip = {
        "id": uuid.uuid4(), "asset_id": asset.id, "track_id": "V2",
        "timeline_start": 5, "source_in": 1, "source_out": 3,
    }
    first = TimelineDocument(project_id=project.id, clips=[clip_a])
    second = TimelineDocument(project_id=project.id, clips=[clip_b, new_clip])
    await save_timeline(db_session, project.id, first, 0)
    await save_timeline(db_session, project.id, second, 1)
    diff = await compare_versions(db_session, project.id, 1, 2)
    assert len(diff["added"]) == 1
    assert len(diff["changed"]) == 1
    assert diff["changed"][0]["fields"] == ["timeline_start"]

@pytest.mark.asyncio
async def test_failed_asset_validation_rolls_back_revision(db_session):
    project = Project(title="Rollback")
    db_session.add(project)
    await db_session.flush()
    missing_asset = uuid.uuid4()
    timeline = TimelineDocument(project_id=project.id, clips=[{
        "id": uuid.uuid4(), "asset_id": missing_asset, "track_id": "V1",
        "timeline_start": 0, "source_in": 0, "source_out": 2,
    }])
    with pytest.raises(ValueError):
        async with db_session.begin_nested():
            await save_timeline(db_session, project.id, timeline, 0)
    count = await db_session.scalar(
        select(func.count()).select_from(TimelineVersion).where(TimelineVersion.project_id == project.id)
    )
    assert count == 0
