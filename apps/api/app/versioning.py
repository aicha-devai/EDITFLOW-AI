import hashlib
import json
import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.models import Asset, Project, TimelineAssetReference, TimelineVersion
from app.schemas import TimelineDocument

class VersionConflict(Exception):
    pass

class ProjectNotFound(Exception):
    pass

def canonical_timeline(timeline: TimelineDocument) -> dict:
    data = timeline.model_dump(mode="json")
    data["version"] = 0
    return data

def timeline_hash(data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

async def _retain_assets(session: AsyncSession, version_id: uuid.UUID, project_id: uuid.UUID, data: dict):
    asset_ids = {uuid.UUID(clip["asset_id"]) for clip in data.get("clips", [])}
    if not asset_ids:
        return
    rows = await session.execute(select(Asset.id).where(Asset.project_id == project_id, Asset.id.in_(asset_ids)))
    found = set(rows.scalars().all())
    missing = asset_ids - found
    if missing:
        raise ValueError(f"Timeline references assets not belonging to this project: {sorted(map(str, missing))}")
    session.add_all([
        TimelineAssetReference(timeline_version_id=version_id, asset_id=asset_id)
        for asset_id in sorted(asset_ids, key=str)
    ])

async def save_timeline(
    session: AsyncSession,
    project_id: uuid.UUID,
    timeline: TimelineDocument,
    expected_version: int | None,
    message: str | None = None,
    restored_from_version_id: uuid.UUID | None = None,
):
    if timeline.project_id != project_id:
        raise ValueError("timeline.project_id does not match the route project_id")

    # Lock the project row so concurrent writers serialize before version allocation.
    project = await session.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise ProjectNotFound()

    latest = await session.scalar(
        select(TimelineVersion).where(TimelineVersion.project_id == project_id)
        .order_by(TimelineVersion.version.desc()).limit(1)
    )
    latest_number = latest.version if latest else 0
    if expected_version is not None and expected_version != latest_number:
        raise VersionConflict(f"Expected version {expected_version}, current version is {latest_number}")

    data = canonical_timeline(timeline)
    digest = timeline_hash(data)

    # An identical timeline is a no-op; do not create a duplicate revision.
    if latest and latest.content_hash == digest:
        return latest, False

    new_version = latest_number + 1
    row = TimelineVersion(
        project_id=project_id,
        version=new_version,
        parent_version_id=latest.id if latest else None,
        timeline_json={**data, "version": new_version},
        content_hash=digest,
        restored_from_version_id=restored_from_version_id,
        message=message,
    )
    session.add(row)
    await session.flush()
    await _retain_assets(session, row.id, project_id, data)
    project.current_version_id = row.id
    await session.flush()
    return row, True

async def list_versions(session: AsyncSession, project_id: uuid.UUID):
    return list((await session.scalars(
        select(TimelineVersion).where(TimelineVersion.project_id == project_id)
        .order_by(TimelineVersion.version.asc())
    )).all())

async def compare_versions(session: AsyncSession, project_id: uuid.UUID, from_version: int, to_version: int):
    rows = (await session.scalars(
        select(TimelineVersion).where(
            TimelineVersion.project_id == project_id,
            TimelineVersion.version.in_([from_version, to_version]),
        )
    )).all()
    by_number = {r.version: r for r in rows}
    if from_version not in by_number or to_version not in by_number:
        raise LookupError("One or both versions do not exist")
    before = {c["id"]: c for c in by_number[from_version].timeline_json.get("clips", [])}
    after = {c["id"]: c for c in by_number[to_version].timeline_json.get("clips", [])}
    added = [after[k] for k in after.keys() - before.keys()]
    removed = [before[k] for k in before.keys() - after.keys()]
    changed = []
    for key in before.keys() & after.keys():
        fields = sorted(k for k in set(before[key]) | set(after[key]) if before[key].get(k) != after[key].get(k))
        if fields:
            changed.append({"clip_id": key, "fields": fields, "before": before[key], "after": after[key]})
    return {"from_version": from_version, "to_version": to_version, "added": added, "removed": removed, "changed": changed}

async def restore_version(session: AsyncSession, project_id: uuid.UUID, source_version: int, expected_version: int, message: str | None = None):
    source = await session.scalar(select(TimelineVersion).where(
        TimelineVersion.project_id == project_id, TimelineVersion.version == source_version
    ))
    if source is None:
        raise LookupError("Source version does not exist")
    timeline = TimelineDocument.model_validate(source.timeline_json)
    return await save_timeline(
        session, project_id, timeline, expected_version,
        message=message or f"Restored from version {source_version}",
        restored_from_version_id=source.id,
    )
