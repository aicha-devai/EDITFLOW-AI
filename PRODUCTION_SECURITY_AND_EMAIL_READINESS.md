# Production security and email readiness review

Status: **NOT APPROVED FOR PUBLIC LAUNCH** until every blocker below is closed and the production deployment is verified.

This review reflects repository code and CI evidence only. It does not assert that production infrastructure, DNS, SMTP delivery, or customer ownership records have been inspected.

## Implemented in the repository

- Production startup validation fails closed unless a 32+ character auth secret, explicit HTTPS frontend origin, explicit HTTPS CORS origins, authenticated TLS SMTP, a non-local database, and S3-compatible storage are configured.
- SMTP refuses plaintext transport and incomplete username/password pairs; SSL and STARTTLS use the system CA trust store for certificate verification.
- Verification and password-reset tokens are invalidated if delivery fails, rather than remaining live with no delivered link.
- New invitations revoke prior unaccepted invitations for the same project and email; invitation creation is rate-limited by project, recipient, and request IP.
- Registration responses no longer disclose whether an email already has an account.
- Authentication and invitation API responses use `Cache-Control: no-store`; API security headers include `nosniff`, `DENY` framing, a restrictive referrer policy, and a Permissions Policy.
- Account-action links place one-time tokens in URL fragments (not sent in HTTP requests), set a no-referrer policy, and remove the token from visible URL/history after reading it.
- Browser authentication now supports HttpOnly access/refresh cookies, SameSite=Lax, Secure cookies in production, CSRF double-submit validation on cookie-authenticated state changes, and credentialed CORS for explicitly allowlisted origins. The frontend and invitation flow no longer persist bearer tokens in sessionStorage; only the account email remains in tab storage.
- Legacy ownership tools remain admin-only CLI utilities; preview is the default and `--apply` is required for a database write.

## Production configuration

Inject values through the deployment secret manager. Do not commit them to Git or paste secrets into issue trackers or chat.

Required environment variables:

- `EDITFLOW_ENV=production`
- `EDITFLOW_AUTH_SECRET`: random secret with at least 32 bytes of entropy (prefer 48+ random bytes).
- `DATABASE_URL`: managed PostgreSQL endpoint, not localhost, with `?ssl=require` (or an approved `sslmode=require/verify-full`) configured.
- `EDITFLOW_EMAIL_SMTP_HOST`, `EDITFLOW_EMAIL_SMTP_PORT`, `EDITFLOW_EMAIL_SMTP_USERNAME`, `EDITFLOW_EMAIL_SMTP_PASSWORD`, `EDITFLOW_EMAIL_FROM`.
- Select exactly one SMTP transport: `EDITFLOW_EMAIL_STARTTLS=true` with `EDITFLOW_EMAIL_USE_SSL=false`, or implicit TLS with the inverse values.
- `EDITFLOW_EMAIL_PUBLIC_URL=https://<frontend-host>`.
- `EDITFLOW_CORS_ORIGINS=https://<frontend-host>` (comma-separated explicit HTTPS origins only).
- `EDITFLOW_STORAGE_BACKEND=s3`, `S3_BUCKET`, and the cloud identity/credentials required by the selected S3 provider.

The production validator rejects localhost database URLs, missing explicit database TLS, development CORS origins, HTTP email links, plaintext SMTP, missing SMTP credentials, and local-file storage.

## Blockers that still require production access or product decisions

1. **Legacy ownership inventory and claims:** run `python scripts/list_legacy_projects.py` against the production database in a controlled admin session. Independently verify each claimant against original records. For each approved project, run `claim_legacy_project.py` without `--apply`, review the result, obtain a second-person approval, then repeat with `--apply`. Save the project UUID, ticket reference, operator, reason, and resulting audit event in the support case. No production rows have been inspected or changed by this review.
2. **SMTP delivery and domain reputation:** configure a real provider, verify sender/domain ownership, publish provider-issued SPF and DKIM records, publish a DMARC policy, then test registration, verification, resend, password reset, and invitations to controlled mailboxes. Confirm inbox delivery, links, expiry, bounce handling, and suppression behavior. CI mocks email and does not prove deliverability.
3. **Same-site deployment and browser verification:** deploy the frontend and API on the same site and preferably one origin. The production frontend now defaults API calls to its own origin; configure the reverse proxy to route `/v1/*` and `/health` to the API while serving the web build and `/auth-action.html` from the frontend. Confirm the proxy forwards `Set-Cookie` and `Cookie` and preserves HTTPS so SameSite=Lax cookies work reliably. Run browser tests against the deployed HTTPS hostname for login, reload persistence, refresh rotation, logout, invitation acceptance, and CSRF rejection. The repository implementation is present, but production-host verification is still pending.
4. **Ingress and transport:** terminate TLS at a managed reverse proxy/load balancer, redirect HTTP to HTTPS, enable HSTS there, restrict direct access to API/worker/database ports, and configure trusted proxy IPs explicitly. Do not trust arbitrary `X-Forwarded-For` values. The current Compose file is a development stack, not a hardened public deployment.
5. **Database operations:** configure automated encrypted backups, retention, restore drills, least-privilege database users, migration review, and monitoring. The Compose development database credentials must never be reused in production.
6. **Operational controls:** add security event monitoring, SMTP failure alerts, abuse monitoring, dependency/container scanning, and an incident-response contact/process. Verify account deletion/retention policy before exposing destructive account operations.

## SMTP smoke test

After production secrets are configured, send one message only to a mailbox controlled by the operator:

```bash
python scripts/send_test_email.py controlled-mailbox@example.com --send
```

The command refuses to send unless `--send` is present. Confirm actual inbox placement, spam placement, provider delivery logs, SPF, DKIM and DMARC alignment. A successful SMTP response alone does not guarantee inbox delivery.

## Controlled legacy ownership runbook

Run from `apps/api` with a read-only inventory connection first:

```bash
python scripts/list_legacy_projects.py
```

For each candidate, independently verify the destination user is active and email-verified. Preview:

```bash
python scripts/claim_legacy_project.py PROJECT_UUID owner@example.com \
  --operator "SUPPORT-CASE-123" \
  --reason "Verified against original invoice and account records"
```

Only after the preview is checked and approved by a second operator, execute the same command with `--apply`. Confirm the new owner and `ownership.claimed` audit event by querying the production database. Never bulk-claim by matching display names or unverified email addresses.

## CI evidence

The repository's previous CI run passed 7/7 Playwright tests and 122 backend tests (1 skipped, 1 warning). That result is code-level test evidence only; it is not a production deployment, SMTP, backup/restore, or ownership-migration sign-off.


## Deployment artifacts added in the repository

- `docker-compose.production.yml` is a standalone production topology: the API and render worker use managed PostgreSQL with TLS and S3-compatible storage; only the Nginx ingress publishes ports 80/443.
- `deploy/nginx.conf` redirects HTTP to HTTPS, serves the frontend through the web container, and proxies `/v1/*` and `/health` to the API. It forwards the original client address only from this ingress and sets the external scheme to HTTPS.
- `apps/web/Dockerfile` builds the web app into a small Nginx image.
- Mount a valid certificate/key pair at `deploy/tls/fullchain.pem` and `deploy/tls/privkey.pem` before starting the stack. The configured certificate must cover the public hostname. Replace the default Nginx `server_name _` with the exact hostname before deployment.
- Start with `docker compose -f docker-compose.production.yml config`, then `docker compose -f docker-compose.production.yml up -d --build`. Inject all required values through a secret manager; never commit a production `.env`.

### HTTPS and browser session verification (must run against the real hostname)

1. Confirm the DNS A/AAAA records point to the ingress and the certificate hostname, chain, and expiry are valid.
2. Confirm `curl -I http://YOUR_HOST/` returns a redirect to HTTPS and `curl -fsS https://YOUR_HOST/health` returns a healthy API response.
3. In a clean browser profile, register/verify a controlled account, log in, reload, and confirm the session persists without access/refresh tokens in localStorage or sessionStorage.
4. Confirm access and refresh cookies are `HttpOnly; Secure; SameSite=Lax`; the CSRF cookie is readable but its value is required in `X-CSRF-Token` for state-changing cookie-authenticated requests.
5. Confirm refresh rotation, logout invalidation, invitation acceptance, and a rejected mutation without a matching CSRF token. Repeat from the exact production origin.
6. Confirm API and database ports are not publicly reachable. Only ingress ports 80/443 should be exposed.

### Real email authentication and domain DNS verification

Use the SMTP provider's exact domain-verification, SPF, DKIM and DMARC instructions. Do not publish guessed SPF or DKIM values. Ensure there is only one SPF TXT policy at the apex, publish every provider-issued DKIM selector, and start DMARC with a monitored policy appropriate to the domain's existing senders. Raise enforcement only after reviewing aggregate reports and confirming alignment.

Send controlled messages through registration, verification, resend, password reset and project invitations. For each, inspect provider delivery logs and recipient inbox/spam placement, confirm SPF and DKIM pass and align with the visible From domain, confirm DMARC pass, and test expiry and one-time use of links. A successful SMTP submission is not proof of inbox placement.

### Backup and restore drill

The repository now includes encrypted backup and guarded restore utilities. Install PostgreSQL client tools and the `age` utility on the backup host.

Create an encrypted backup:

```bash
cd apps/api
export DATABASE_URL='postgresql+asyncpg://...'
export BACKUP_AGE_RECIPIENT='age1...'
python scripts/backup_postgres.py --output-dir /secure-backup-staging
```

The backup command creates a PostgreSQL custom-format archive, validates it with `pg_restore --list`, encrypts it with the age recipient public key, and writes a SHA-256 metadata file for the encrypted archive. Keep the age identity private key outside the backup host and store both archive and metadata in access-controlled off-host storage with immutable retention and alerting. Schedule this command (or the managed database provider's equivalent) at the required RPO; this script is a backup primitive, not a scheduler or off-site storage service.

For a restore drill, provision a separate empty database whose name contains `restore` or `drill`, then run:

```bash
cd apps/api
export RESTORE_DATABASE_URL='postgresql+asyncpg://.../editflow_restore?ssl=require'
export AGE_IDENTITY_FILE='/secure/keys/editflow-backup-identity.txt'
python scripts/restore_postgres.py /secure-backup-staging/editflow-TIMESTAMP.dump.age --allow-overwrite
```

The restore script checks the encrypted archive checksum and metadata, decrypts to a mode-0600 temporary file, validates the archive listing, and refuses target database names that do not contain `restore` or `drill`. It is still destructive to that target database. After restore, run Alembic status, application smoke tests, project/asset counts, and representative render/media reads. Record duration and achieved RPO/RTO. Never restore over production as part of a drill.

### Legacy project ownership migration

The production inventory and claim scripts are present, but no production database was connected in this environment. Run the read-only inventory first. Independently verify each claimant against source-of-truth evidence and obtain documented second-person approval for each individual project. Use dry-run, review output, then `--apply` one project at a time. Verify the owner and `ownership.claimed` audit event after each commit. Do not run a bulk transfer.

## Current execution state

The deployment, proxy, backup and restore tooling is committed, but it has not been exercised against a real hostname, SMTP provider, production database, object store, or production backup target. Those are external verification gates, not code-completion checkboxes. Do not approve public launch until the evidence for every gate above is attached to the release record.
