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
- `EDITFLOW_AUTH_LOGIN_LIMIT`: failed/successful login requests per IP per window; default 10.
- `EDITFLOW_AUTH_REGISTER_LIMIT`: registration requests per IP per window; default 5.
- `EDITFLOW_AUTH_LOGIN_WINDOW_SECONDS`: login window; default 900 seconds.
- `EDITFLOW_AUTH_REGISTER_WINDOW_SECONDS`: registration window; default 3600 seconds.

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

1. Abuse monitoring, alerting, and adaptive controls beyond the baseline login/register rate limits now implemented.
2. Email verification and secure password-reset flows.
3. Email-based invitations; membership changes are now recorded in the owner-only project audit log.
4. Administrative recovery/ownership transfer for legacy projects.
5. Production HTTPS, secret-manager configuration, backups, and security monitoring.

The API should not be considered public-launch ready until these controls are completed and reviewed.


## Authentication rate limiting

Migration `0008_auth_rate_limits` adds persistent PostgreSQL fixed-window counters. Login attempts are counted against both the source IP and the IP/email pair; registration attempts are counted against the source IP. Scope identifiers are HMAC-SHA256 digests keyed by the authentication secret, so raw email addresses and IP addresses are not stored in the limiter table. Requests over the configured limit receive HTTP 429 with a `Retry-After` header. Counters are shared across API workers because they are stored in PostgreSQL.

The current implementation uses the ASGI connection's client address. If the API is deployed behind a reverse proxy, configure the proxy/server to set trusted client addresses correctly; do not trust arbitrary forwarded-IP headers. Operational abuse monitoring, alerting, and adaptive risk controls remain deployment tasks.


## Project membership audit log

Migration `0009_project_audit_log` adds an append-only event record for membership additions, role changes, and removals. Each event captures the acting owner, target account, action, previous/new role, and timestamp. Email snapshots remain available if an account is later deleted. The owner can inspect the log at `GET /v1/projects/{project_id}/audit-log`; other project members cannot read administrative audit history. Re-submitting an unchanged role does not create a redundant event.


## Email verification, password reset and project invitations

Configure these secrets/environment values in the API deployment:
- `EDITFLOW_EMAIL_SMTP_HOST`, `EDITFLOW_EMAIL_SMTP_PORT` (default 587)
- `EDITFLOW_EMAIL_SMTP_USERNAME`, `EDITFLOW_EMAIL_SMTP_PASSWORD`
- `EDITFLOW_EMAIL_FROM`
- `EDITFLOW_EMAIL_USE_SSL` (default false), `EDITFLOW_EMAIL_STARTTLS` (default true)
- `EDITFLOW_EMAIL_PUBLIC_URL` (frontend origin used to construct links)

New registrations are unverified and cannot log in until `POST /v1/auth/verify-email` consumes their 24-hour token. Resend is available through `POST /v1/auth/resend-verification`. Password reset uses `POST /v1/auth/request-password-reset` and `POST /v1/auth/reset-password`; reset tokens expire after 30 minutes, are single-use, and revoke every active refresh session for the account. Responses do not reveal whether an email exists.

Owners can invite any email with `POST /v1/projects/{project_id}/invitations`. Invitations expire after seven days. The invited person must sign in with a verified account whose email exactly matches the invitation, then call `POST /v1/invitations/accept`. Acceptance grants the role and is written to the project audit log. Tokens are stored only as SHA-256 hashes.

Migration `0010_email_and_invitations` preserves pre-existing accounts as verified to avoid locking out existing users; new registrations explicitly start unverified. SMTP delivery must be configured and verified in the deployment environment. The backend test suite mocks the mail transport and does not prove that a real provider accepts or delivers messages.
