# Legacy project ownership recovery

Projects created before authenticated ownership was introduced may have `projects.owner_id = NULL`.
They are intentionally not claimable through the public API: a project UUID alone is not proof of ownership.

## Recovery policy

1. Verify the claimant independently against original account records, billing records, or a documented customer support case.
2. Confirm the destination account exists, is active, and has a verified email address.
3. Run the claim utility in dry-run mode first. It refuses to overwrite any project that already has an owner.
4. Review the project UUID, destination email, operator/ticket reference, and verification reason.
5. Re-run with `--apply` only after approval. The update and `ownership.claimed` audit event are committed in the same database transaction.

The utility does not delete assets, timeline versions, render jobs, or project members. It only sets the owner of an ownerless project and records the operator and reason in the audit log.

## Commands

Run from `apps/api` with the production database connection configured through the normal secret manager:

```bash
python scripts/claim_legacy_project.py PROJECT_UUID verified-owner@example.com \
  --operator "SUPPORT-CASE-123" \
  --reason "Matched original purchase receipt and account email"
```

The command above is a dry run. After reviewing its output and obtaining approval:

```bash
python scripts/claim_legacy_project.py PROJECT_UUID verified-owner@example.com \
  --operator "SUPPORT-CASE-123" \
  --reason "Matched original purchase receipt and account email" \
  --apply
```

Never put database credentials or customer evidence in source control or chat. Execute the command only from a trusted administrative environment. Keep the case reference, not sensitive documents, in the audit reason.
