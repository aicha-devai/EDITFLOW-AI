"""List legacy projects that still have no recorded owner.

Run from apps/api in a trusted administrative environment:
  python scripts/list_legacy_projects.py
This command is read-only and prints JSON for an internal ownership-recovery review.
"""
import asyncio
import json

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Project


async def main():
    async with SessionLocal() as db:
        projects = (await db.execute(
            select(Project)
            .where(Project.owner_id.is_(None))
            .order_by(Project.created_at, Project.id)
        )).scalars().all()
        print(json.dumps([
            {
                "project_id": str(project.id),
                "title": project.title,
                "created_at": project.created_at.isoformat() if project.created_at else None,
            }
            for project in projects
        ], ensure_ascii=False, indent=2))
        print(f"\nTotal unassigned projects: {len(projects)}")


if __name__ == "__main__":
    asyncio.run(main())
