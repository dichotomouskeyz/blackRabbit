"""029 create user_role_permission_log table

Revision ID: 029_user_role_permission_log
Revises: 028_data_lock_log
Create Date: 2026-05-04

WHY THIS IS DIFFERENT FROM SYSTEM_USER_ACCESS_LOG:
  system_user_access_log (migration 021) tracks WHO has access to
  Consensai at the role level — coordinator, monitor, data_manager, etc.

  user_role_permission_log tracks CAPABILITY-LEVEL grants and revocations
  — fine-grained permissions that apply within a role. For example:
    - A coordinator's role is set in system_users. Their specific ability
      to authorize data exports for session X is a capability permission.
    - During an investigation, a user's unblinding access might be suspended
      without changing their overall role.
    - Temporary elevated access for a data lock activity is time-bounded.

  21 CFR Part 11 Section 11.10(d) requires limiting access to only those
  with authority. This table provides the evidence that the authorization
  architecture operates at a granular, auditable level — not just broad
  role assignment.

PERMISSION_TYPE VOCABULARY:
  'data_export'         — authorize formal data exports
  'audit_review'        — access the audit trail for review
  'alert_acknowledge'   — acknowledge safety alerts
  'session_close'       — formally close a session record
  'dose_approve'        — approve dose administration
  'unblinding_access'   — access to randomization/treatment arm data
  'regulatory_report'   — submit FDA/IRB regulatory reports
  'data_lock'           — lock or unlock the clinical database
  'data_correction'     — approve data corrections and amendments
  'admin_override'      — bypass standard application access controls

RESOURCE_SCOPE:
  Allows permission grants to be scoped to a specific resource, e.g.:
    - session_id for session-level permissions
    - a table name for table-level locks
    - NULL means the permission applies across all resources for this user
"""

from typing import Sequence, Union

from alembic import op

revision: str = "029_user_role_permission_log"
down_revision: Union[str, None] = "028_data_lock_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE user_role_permission_log (
            id                  BIGSERIAL   PRIMARY KEY,
            user_id             TEXT        NOT NULL,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            permission_type     TEXT        NOT NULL
                                CHECK (permission_type IN (
                                    'data_export',
                                    'audit_review',
                                    'alert_acknowledge',
                                    'session_close',
                                    'dose_approve',
                                    'unblinding_access',
                                    'regulatory_report',
                                    'data_lock',
                                    'data_correction',
                                    'admin_override'
                                )),
            resource_scope      TEXT,
            action              TEXT        NOT NULL
                                CHECK (action IN (
                                    'granted',
                                    'revoked',
                                    'modified',
                                    'expired'
                                )),
            previous_permission TEXT,
            granted_by          TEXT        NOT NULL,
            reason              TEXT,
            expires_at          TIMESTAMPTZ,
            effective_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("REVOKE UPDATE, DELETE ON user_role_permission_log FROM PUBLIC;")

    op.execute("""
        CREATE TRIGGER user_role_permission_log_audit_trigger
        AFTER INSERT ON user_role_permission_log
        FOR EACH ROW
        EXECUTE FUNCTION audit_trigger_full_func();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS user_role_permission_log_audit_trigger "
        "ON user_role_permission_log;"
    )
    op.execute("DROP TABLE IF EXISTS user_role_permission_log;")
