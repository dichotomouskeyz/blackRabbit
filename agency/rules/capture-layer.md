# Capture Layer Rules

- LSL samples are written to XDF before database writes.
- DB connection loss should buffer or reconcile from XDF, not drop silently.
- `lsl_timestamp` comes from LSL/device time.
- `db_insert_time` comes from database insertion time.
- Capture code should not perform post-session analysis.
