"""Safely claim a legacy project whose owner_id is NULL.

Run from apps/api:
  python scripts/claim_legacy_project.py PROJECT_UUID verified-owner@example.com \
      --operator "ops-ticket-123" --reason "Verified original customer request"
Add --apply to commit. Without it, the command performs a dry run and rolls back.
"""
import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Project, ProjectAuditEvent, User


async def claim_legacy_project(db: AsyncSession, project_id: UUID, owner_email: str, operator: str, reason: str, apply: bool = False):
    project = await db.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    if project is None:
        raise ValueError("Project not found.")
    if project.owner_id is not None:
        raise ValueError("Refusing: project already has an owner; this tool only claims ownerless legacy projects.")
    owner = await db.scalar(
        select(User).where(
            User.email == owner_email.strip().lower(),
            User.is_active.is_(True),
            User.is_email_verified.is_(True),
        )
    )
    if owner is None:
        raise ValueError("Refusing: no active, email-verified account matches the supplied owner email.")

    project.owner_id = owner.id
    db.add(ProjectAuditEvent(
        project_id=project.id,
        actor_user_id=None,
        actor_email="admin:" + operator.strip(),
        target_user_id=owner.id,
        target_email=owner.email,
        action="ownership.claimed",
        previous_role="unassigned",
        new_role="owner",
        details=reason.strip(),
    ))
    if apply:
        await db.commit()
        return {"applied": True, "project_id": str(project.id), "owner_email": owner.email}
    await db.rollback()
    return {"applied": False, "dry_run": True, "project_id": str(project.id), "owner_email": owner.email}


async def run_claim(project_id: UUID, owner_email: str, operator: str, reason: str, apply: bool = False):
    async with SessionLocal() as db:
        return await claim_legacy_project(db, project_id, owner_email, operator, reason, apply)

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_id", type=UUID)
    parser.add_argument("owner_email")
    parser.add_argument("--operator", required=True, help="Internal ticket or operator identifier for the audit log")
    parser.add_argument("--reason", required=True, help="How ownership was independently verified")
    parser.add_argument("--apply", action="store_true", help="Commit the ownership claim; otherwise dry-run only")
    args = parser.parse_args()
    if not args.operator.strip() or not args.reason.strip():
        parser.error("--operator and --reason must not be blank")
    result = await run_claim(args.project_id, args.owner_email, args.operator, args.reason, args.apply)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
