import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RateLimitBucket


def _scope_digest(scope: str) -> str:
    secret = settings.auth_secret
    if not secret or len(secret.encode("utf-8")) < 32:
        raise HTTPException(503, "Authentication is not configured")
    return hmac.new(secret.encode("utf-8"), scope.encode("utf-8"), hashlib.sha256).hexdigest()


async def enforce_rate_limit(
    db: AsyncSession,
    scopes: list[str],
    limit: int,
    window_seconds: int,
) -> None:
    """Atomically count requests in a fixed window, shared by all API workers."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=window_seconds)
    for scope in scopes:
        key = _scope_digest(scope)
        statement = insert(RateLimitBucket).values(
            scope_key=key,
            window_started_at=now,
            request_count=1,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[RateLimitBucket.scope_key],
            set_={
                "window_started_at": case(
                    (RateLimitBucket.window_started_at <= cutoff, now),
                    else_=RateLimitBucket.window_started_at,
                ),
                "request_count": case(
                    (RateLimitBucket.window_started_at <= cutoff, 1),
                    else_=RateLimitBucket.request_count + 1,
                ),
            },
        ).returning(RateLimitBucket.request_count, RateLimitBucket.window_started_at)
        count, started_at = (await db.execute(statement)).one()
        await db.commit()
        if count > limit:
            retry_after = max(1, int((started_at + timedelta(seconds=window_seconds) - now).total_seconds()))
            raise HTTPException(
                status_code=429,
                detail="Too many authentication attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
