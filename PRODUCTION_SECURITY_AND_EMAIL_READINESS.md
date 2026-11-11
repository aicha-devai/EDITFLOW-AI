# Production security and email readiness review

Status: **NOT APPROVED FOR PUBLIC LAUNCH** until every blocker below is closed and the production deployment is verified.

This review reflects repository code and CI evidence only. It does not assert that production infrastructure, DNS, SMTP delivery, or customer ownership records have been inspected.

## Implemented in the repository

- Production startup validation fails closed unless a 32+ character auth secret, explicit HTTPS frontend origin, explicit HTTPS CORS origins, authenticated TLS SMTP, a non-local database, and S3-compatible storage are configured.
- SMTP refuses plaintext transport and incomplete username/password pairs.
- Verification and password-reset tokens are invalidated if delivery fails, rather than remaining live with no delivered link.
- New invitations revoke prior unaccepted invitations for the same project and email; invitation creation is rate-limited by project, recipient, and request IP.
- Registration responses no longer disclose whether an email already has an account.
- Authentication and invitation API responses use `Cache-Control: no-store`; API security headers include `nosniff`, `DENY` framing, a restrictive referrer policy, and a Permissions Policy.
- Account-action pages set a no-referrer policy and remove the one-time token from the visible URL/history after reading it.
- Legacy ownership tools remain admin-only CLI utilities; preview is the default and `--apply` is required for a database write.

## Production configuration

Inject values through the deployment secret manager. Do not commit them to Git or paste secrets into issue trackers or chat.

Required environment variables:

- `EDITFLOW_ENV=production`
- `EDITFLOW_AUTH_SECRET`: random secret with at least 32 bytes of entropy (prefer 48+ random bytes).
- `DATABASE_URL`: managed PostgreSQL endpoint, not localhost; require TLS at the database provider/driver.
- `EDITFLOW_EMAIL_SMTP_HOST`, `EDITFLOW_EMAIL_SMTP_PORT`, `EDITFLOW_EMAIL_SMTP_USERNAME`, `EDITFLOW_EMAIL_SMTP_PASSWORD`, `EDITFLOW_EMAIL_FROM`.
- Select exactly one SMTP transport: `EDITFLOW_EMAIL_STARTTLS=true` with `EDITFLOW_EMAIL_USE_SSL=false`, or implicit TLS with the inverse values.
- `EDITFLOW_EMAIL_PUBLIC_URL=https://<frontend-host>`.
- `EDITFLOW_CORS_ORIGINS=https://<frontend-host>` (comma-separated explicit HTTPS origins only).
- `EDITFLOW_STORAGE_BACKEND=s3`, `S3_BUCKET`, and the cloud identity/credentials required by the selected S3 provider.

The production validator rejects localhost database URLs, development CORS origins, HTTP email links, plaintext SMTP, missing SMTP credentials, and local-file storage.

## Blockers that still require production access or product decisions

1. **Legacy ownership inventory and claims:** run `python scripts/list_legacy_projects.py` against the production database in a controlled admin session. Independently verify each claimant against original records. For each approved project, run `claim_legacy_project.py` without `--apply`, review the result, obtain a second-person approval, then repeat with `--apply`. Save the project UUID, ticket reference, operator, reason, and resulting audit event in the support case. No production rows have been inspected or changed by this review.
2. **SMTP delivery and domain reputation:** configure a real provider, verify sender/domain ownership, publish provider-issued SPF and DKIM records, publish a DMARC policy, then test registration, verification, resend, password reset, and invitations to controlled mailboxes. Confirm inbox delivery, links, expiry, bounce handling, and suppression behavior. CI mocks email and does not prove deliverability.
3. **Browser session architecture:** the current web client stores access and refresh tokens in `sessionStorage`. This is exposed to JavaScript and therefore to an XSS compromise. Before a public launch, move refresh credentials to Secure, HttpOnly, SameSite cookies through a backend-for-frontend or equivalent design; add CSRF protection for cookie-authenticated state changes and test rotation/revocation in a real browser.
4. **Ingress and transport:** terminate TLS at a managed reverse proxy/load balancer, redirect HTTP to HTTPS, enable HSTS there, restrict direct access to API/worker/database ports, and configure trusted proxy IPs explicitly. Do not trust arbitrary `X-Forwarded-For` values. The current Compose file is a development stack, not a hardened public deployment.
5. **Database operations:** configure automated encrypted backups, retention, restore drills, least-privilege database users, migration review, and monitoring. The Compose development database credentials must never be reused in production.
6. **Operational controls:** add security event monitoring, SMTP failure alerts, abuse monitoring, dependency/container scanning, and an incident-response contact/process. Verify account deletion/retention policy before exposing destructive account operations.

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
