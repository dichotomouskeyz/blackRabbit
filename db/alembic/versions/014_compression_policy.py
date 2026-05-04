"""014 add auto-compression policy on all hypertables

Revision ID: 014_compression_policy
Revises: 013_compression
Create Date: 2026-04-27

WHY A POLICY INSTEAD OF MANUAL COMPRESSION:
  Migration 013 enabled compression settings on each table.
  But compression doesn't happen automatically — you need a policy
  that tells TimescaleDB WHEN to compress.

  A compression policy is a background job that runs on a schedule
  and compresses any chunk older than the specified interval.

  Without a policy, chunks stay uncompressed forever unless you
  manually run SELECT compress_chunk(...) yourself. That's not
  acceptable for a clinical system — you can't rely on manual steps
  for data management during a session.

WHY COMPRESS_AFTER = 1 DAY:
  The policy compresses chunks older than 1 day. This means:
    - During a session: data stays uncompressed, fully writable,
      fast for real-time queries
    - After a session closes: within 24 hours, the chunk is
      compressed automatically

  You cannot write to a compressed chunk — that's why we don't
  compress during the session. The 1-day buffer ensures the session
  is always fully closed before compression touches its data.

  For UCSF demos: a session runs, closes, and within 24 hours
  storage is reduced by ~80%. No manual intervention required.

WHY THIS IS A SEPARATE MIGRATION FROM 013:
  Conceptually separate concerns:
    013 = "here is HOW to compress this table"
    014 = "here is WHEN to compress this table"

  Keeping them separate makes it easier to change the policy
  (e.g., compress after 7 days instead of 1 day) without
  touching the compression settings themselves.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "014_compression_policy"
down_revision: Union[str, None] = "013_compression"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HYPERTABLES = [
    "eeg_samples",
    "hrv_samples",
    "eda_samples",
    "respiration_samples",
]


def upgrade() -> None:
    for table in HYPERTABLES:
        op.execute(f"""
            SELECT add_compression_policy(
                '{table}',
                compress_after => INTERVAL '1 day'
            );
        """)


def downgrade() -> None:
    for table in HYPERTABLES:
        op.execute(f"""
            SELECT remove_compression_policy('{table}');
        """)
