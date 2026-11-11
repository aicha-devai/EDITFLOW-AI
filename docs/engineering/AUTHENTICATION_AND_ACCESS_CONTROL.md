# Authentication and project access control

## Authentication

- `POST /v1/auth/register` creates an account and returns a short-lived access token plus a refresh token.
- `POST /v1/auth/login` verifies the password and creates a new refresh-token session.
- `GET /v1/auth/me` returns the authenticated account.
- `POST /v1/auth/refresh` rotates a refresh token. The previous token is invalidated.
- `POST /v1/auth/logout` revokes the refresh-token family for that device/session.
- Access tokens are signed HS256 JWTs with a 15-minute default lifetime.
- Refresh tokens are opaque random values. Only SHA-256 hashes are stored in PostgreSQL.
- Reuse of an already-rotated refresh token revokes every active token in that session family.
- Passwords are hashed with PBKDF2-HMAC-SHA256, a per-password random salt, and 600,000 iterations.

## Required configuration

Set `EDITFLOW_AUTH_SECRET` to a cryptographically random value of at least 32 characters in the deployment secret manager. Generate one with:

```bash
openssl rand -hex 32
```

Optional settings:

- `EDITFLOW_AUTH_ACCESS_TOKEN_SECONDS`: 300–3600 seconds; default 900.
- `EDITFLOW_AUTH_REFRESH_TOKEN_DAYS`: 1–90 days; default 30.

Authentication fails closed when the signing secret is absent or too short. Do not commit the secret to Git, place it in frontend configuration, or expose it in logs. Serve the API over HTTPS.

## Project roles

- **Owner**: full access; can add, change, list, and remove project members.
- **Editor**: can read and modify project timelines, create/cancel renders, and approve QC intent proposals.
- **Viewer**: read-only access to versions, render status/media, QC suggestions, and the Story Continuity Graph.

Only the owner can manage membership. Members must already have an active EDITFLOW AI account; the owner assigns their registered email the `editor` or `viewer` role. The owner is represented by `projects.owner_id`, not a member row.

Project APIs return 404 when the caller is neither the owner nor a member, avoiding disclosure of another user's project existence. Read-only users receive 403 when attempting an editor-only operation.

## Data migration note

Migration `0005_auth_ownership` adds nullable `projects.owner_id` so existing projects are not deleted or assigned to an arbitrary account. Projects created before this migration remain inaccessible through user-scoped APIs until an authorized administrator performs an explicit ownership-assignment process. Do not automatically assign legacy projects to the first registered user.

## Remaining production hardening

The current implementation establishes authentication, refresh-session rotation, owner/editor/viewer authorization, and automated tests. Before a public multi-user launch, complete and verify:

1. Login/register rate limiting and abuse monitoring.
2. Email verification and secure password-reset flows.
3. Email-based invitations and membership audit history.
4. Administrative recovery/ownership transfer for legacy projects.
5. Production HTTPS, secret-manager configuration, backups, and security monitoring.

The API should not be considered public-launch ready until these controls are completed and reviewed.
