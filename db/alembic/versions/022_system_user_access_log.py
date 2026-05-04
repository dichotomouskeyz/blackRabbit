"""022 create system_user_access_log table

Revision ID: 022_system_user_access_log
Revises: 021_data_access_log
Create Date: 2026-04-27

WHAT THIS TRACKS:
  This is not the same as data_access_log (023).

  data_access_log = who queried what data (read events)
  system_user_access_log = who has access to the system at all,
                           and how that access changed over time

  21 CFR Part 11 requires sponsors to maintain a record of all
  clinical trial personnel authorized to access the electronic
  system, along with changes to any rights or permissions.

  This table answers:
    - Who currently has access to Consensai?
    - When was that access granted and by whom?
    - What role do they have?
    - Has their access ever been modified or revoked?
    - Who was the system administrator who made those changes?

WHY THIS MATTERS FOR UCSF SPECIFICALLY:
  At UCSF, the following people will need system access:
    - Principal Investigator (PI) — read all data, review reports
    - Session coordinators — write HUMeN events, acknowledge alerts
    - Session monitors (therapists) — view live session data
    - Data managers — export data, run reports
    - Site administrators — manage user access

  Each role has different permissions. When a coordinator leaves
  the study, their access must be revoked and documented. If the
  FDA inspects and asks "who had access to participant data during
  the trial?", this table is the answer.

ACCESS_EVENT_TYPE:
  'granted'  — new user given access
  'modified' — existing user's role or permissions changed
  'revoked'  — access removed (staff departure, protocol completion)
  'suspended' — temporary suspension (e.g., pending investigation)
  'reinstated' — access restored after suspension
  'login'    — user logged into the system (session tracking)
  'logout'   — user logged out
"""

from typing import Sequence, Union

from alembic import op

revision: str = "022_system_user_access_log"
down_revision: Union[str, None] = "021_data_access_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # User registry — current state of who has access
    op.execute("""
        CREATE TABLE system_users (
            id                  TEXT        PRIMARY KEY,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            display_name        TEXT        NOT NULL,
            role                TEXT        NOT NULL
                                CHECK (role IN (
                                    'principal_investigator',
                                    'coordinator',
                                    'monitor',
                                    'data_manager',
                                    'site_admin',
                                    'sponsor_admin'
                                )),
            is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
            access_granted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            access_granted_by   TEXT        NOT NULL,
            access_revoked_at   TIMESTAMPTZ,
            access_revoked_by   TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TRIGGER system_users_set_updated_at
        BEFORE UPDATE ON system_users
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    """)

    # Access event log — immutable history of every access change
    op.execute("""
        CREATE TABLE system_user_access_log (
            id                  BIGSERIAL   PRIMARY KEY,
            user_id             TEXT        NOT NULL,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            access_event_type   TEXT        NOT NULL
                                CHECK (access_event_type IN (
                                    'granted',
                                    'modified',
                                    'revoked',
                                    'suspended',
                                    'reinstated',
                                    'login',
                                    'logout'
                                )),
            previous_role       TEXT,
            new_role            TEXT,
            performed_by        TEXT        NOT NULL,
            reason              TEXT,
            ip_address          TEXT,
            event_timestamp     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("REVOKE UPDATE, DELETE ON system_user_access_log FROM PUBLIC;")



def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS system_user_access_log;")
    op.execute("DROP TABLE IF EXISTS system_users;")
