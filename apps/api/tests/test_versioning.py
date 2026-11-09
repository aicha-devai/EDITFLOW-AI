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


@pytest.mark.asyncio
async def test_two_concurrent_writers_serialize_on_project_lock(db_session):
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker

    project = Project(title="Concurrent writers")
    db_session.add(project)
    await db_session.flush()
    project_id = project.id
    initial = TimelineDocument(project_id=project_id, sequence={"revision": 1})
    await save_timeline(db_session, project_id, initial, expected_version=0)
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def writer(revision: int):
        timeline = TimelineDocument(project_id=project_id, sequence={"revision": revision})
        async with factory() as session:
            try:
                async with session.begin():
                    row, created = await save_timeline(
                        session, project_id, timeline, expected_version=1
                    )
                    assert created is True
                    return ("saved", row.version)
            except VersionConflict:
                return ("conflict", None)

    outcomes = await asyncio.gather(writer(2), writer(3))
    assert sorted(result[0] for result in outcomes) == ["conflict", "saved"]
    saved_versions = [result[1] for result in outcomes if result[0] == "saved"]
    assert saved_versions == [2]

    async with factory() as verify:
        count = await verify.scalar(
            select(func.count()).select_from(TimelineVersion)
            .where(TimelineVersion.project_id == project_id)
        )
        assert count == 2


@pytest.mark.asyncio
async def test_render_job_is_pinned_to_immutable_timeline_even_after_new_version(db_session):
    from app.rendering import create_render_job, claim_next_render_job, complete_render_job
    from app.models import RenderJob

    project = Project(title="Pinned render")
    db_session.add(project)
    await db_session.flush()
    v1_doc = TimelineDocument(project_id=project.id, sequence={"fps": 24}, editorial_notes=["original"])
    v1, _ = await save_timeline(db_session, project.id, v1_doc, expected_version=0)
    job, created = await create_render_job(
        db_session, project.id, timeline_version=1,
        render_profile={"resolution": "1080x1920"}, request_key="render-request-1",
    )
    assert created is True
    pinned_version_id = job.timeline_version_id
    pinned_hash = job.timeline_hash
    pinned_snapshot = dict(job.timeline_snapshot)

    v2_doc = TimelineDocument(project_id=project.id, sequence={"fps": 60}, editorial_notes=["later edit"])
    v2, _ = await save_timeline(db_session, project.id, v2_doc, expected_version=1)
    assert v2.id != pinned_version_id
    assert job.timeline_version_id == v1.id
    assert job.timeline_hash == pinned_hash
    assert job.timeline_snapshot == pinned_snapshot
    assert job.timeline_snapshot["sequence"]["fps"] == 24

    claimed = await claim_next_render_job(db_session)
    assert claimed.id == job.id
    assert claimed.status == "running"
    assert claimed.timeline_version_id == v1.id
    assert claimed.timeline_snapshot["sequence"]["fps"] == 24

    finished = await complete_render_job(db_session, job.id, "renders/project-1/job-1.mp4")
    assert finished.status == "succeeded"
    assert finished.output_object_key == "renders/project-1/job-1.mp4"


@pytest.mark.asyncio
async def test_render_job_request_key_is_idempotent(db_session):
    from app.rendering import create_render_job

    project = Project(title="Render idempotency")
    db_session.add(project)
    await db_session.flush()
    doc = TimelineDocument(project_id=project.id, sequence={"fps": 30})
    await save_timeline(db_session, project.id, doc, expected_version=0)
    first, created = await create_render_job(db_session, project.id, request_key="same-render")
    replay, replay_created = await create_render_job(db_session, project.id, request_key="same-render")
    assert created is True
    assert replay_created is False
    assert first.id == replay.id


@pytest.mark.asyncio
async def test_worker_skips_locked_render_jobs(db_session):
    from app.rendering import create_render_job, claim_next_render_job

    project = Project(title="Worker queue")
    db_session.add(project)
    await db_session.flush()
    await save_timeline(
        db_session, project.id,
        TimelineDocument(project_id=project.id, sequence={"fps": 30}),
        expected_version=0,
    )
    await create_render_job(db_session, project.id)
    job = await claim_next_render_job(db_session)
    assert job is not None
    assert job.status == "running"


@pytest.mark.asyncio
async def test_render_job_timeline_pin_is_database_immutable(db_session):
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError
    from app.rendering import create_render_job
    from app.models import RenderJob

    project = Project(title="Immutable render pin")
    db_session.add(project)
    await db_session.flush()
    await save_timeline(
        db_session, project.id,
        TimelineDocument(project_id=project.id, sequence={"fps": 25}),
        expected_version=0,
    )
    job, _ = await create_render_job(db_session, project.id)
    with pytest.raises(DBAPIError):
        await db_session.execute(
            update(RenderJob).where(RenderJob.id == job.id).values(timeline_hash="tampered")
        )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_render_workers_claim_different_jobs_without_double_claim(db_session):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.rendering import create_render_job, claim_next_render_job

    project = Project(title="Parallel render queue")
    db_session.add(project)
    await db_session.flush()
    await save_timeline(
        db_session, project.id,
        TimelineDocument(project_id=project.id, sequence={"fps": 30}),
        expected_version=0,
    )
    first, _ = await create_render_job(db_session, project.id, request_key="queue-a")
    second, _ = await create_render_job(db_session, project.id, request_key="queue-b")
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as worker_a:
        async with worker_a.begin():
            claimed_a = await claim_next_render_job(worker_a)
            assert claimed_a.id in {first.id, second.id}
            async with factory() as worker_b:
                async with worker_b.begin():
                    claimed_b = await claim_next_render_job(worker_b)
                    assert claimed_b.id in {first.id, second.id}
                    assert claimed_b.id != claimed_a.id
