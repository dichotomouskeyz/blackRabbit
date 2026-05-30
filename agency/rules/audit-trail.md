# Audit Trail Rules

- Application code must not insert directly into `audit_events`.
- Database triggers own audit row creation.
- Terminal session status changes write watermarks through triggers.
- High-volume biosignal tables use integrity/reconciliation logs instead of
  per-row audit amplification.
