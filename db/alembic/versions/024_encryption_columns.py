"""024 encryption columns on biosignal hypertables

Revision ID: 024_encryption_columns
Revises: 023_audit_triggers
Create Date: 2026-05-03

WHY ENCRYPTION AT REST:
  Psychedelic trial participants produce highly sensitive biometric data
  (EEG voltage, HRV intervals, EDA conductance, respiration amplitude).
  Under 21 CFR Part 11, HIPAA, and IRB data-security requirements, raw
  biosignal values must be protected at rest — not just in transit.

  Each signal value is encrypted by the forwarder before the DB write,
  so the value is never stored in cleartext. Even a direct DB read by a
  rogue admin yields only ciphertext.

ENCRYPTION SCHEME:
  AES-256-GCM, key derived via PBKDF2-HMAC-SHA256.
  A fresh random salt is generated per sample (stored in `salt`).
  The key derivation configuration is identified by `encryption_key_id`
  so future key rotations can target only the rows that need re-keying.

COLUMNS ADDED (same three columns on every table):
  channel_value_encrypted BYTEA — AES-256-GCM ciphertext of the signal value(s)
  encryption_key_id TEXT        — identifies key derivation config (version + algo)
  salt BYTEA                    — random per-sample PBKDF2 salt

PLAINTEXT COLUMNS DROPPED:
  eeg_samples:          voltage
  hrv_samples:          rr_interval_ms, heart_rate_bpm
  eda_samples:          raw_conductance_us, conductance_us
  respiration_samples:  raw_amplitude, processed_amplitude

  Derived/quality columns (sqi_flag, beat_quality, signal_quality,
  breath_phase, breaths_per_min) are NOT dropped — they contain no
  raw biometric values and are safe to store plaintext.

IMPORTANT: Run this migration on empty biosignal tables.
  The NOT NULL constraint cannot be applied at migration time without
  existing rows causing a failure. Columns are added nullable here;
  lsl_forwarder.py enforces non-null at write time.
  If test rows exist, truncate the four biosignal tables before running.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024_encryption_columns"
down_revision: Union[str, None] = "023_audit_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Plaintext signal columns removed per table.
# Retained here so downgrade() can restore them (as nullable — data is gone).
PLAINTEXT_COLUMNS: dict[str, list[tuple[str, sa.types.TypeEngine]]] = {
    "eeg_samples": [
        ("voltage", sa.Float()),
    ],
    "hrv_samples": [
        ("rr_interval_ms", sa.Float()),
        ("heart_rate_bpm", sa.Float()),
    ],
    "eda_samples": [
        ("raw_conductance_us", sa.Float()),
        ("conductance_us", sa.Float()),
    ],
    "respiration_samples": [
        ("raw_amplitude", sa.Float()),
        ("processed_amplitude", sa.Float()),
    ],
}


def upgrade() -> None:
    for table in PLAINTEXT_COLUMNS:
        op.add_column(table, sa.Column("channel_value_encrypted", sa.LargeBinary(), nullable=True))
        op.add_column(table, sa.Column("encryption_key_id", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("salt", sa.LargeBinary(), nullable=True))

        for col_name, _ in PLAINTEXT_COLUMNS[table]:
            op.drop_column(table, col_name)


def downgrade() -> None:
    for table, columns in PLAINTEXT_COLUMNS.items():
        op.drop_column(table, "channel_value_encrypted")
        op.drop_column(table, "encryption_key_id")
        op.drop_column(table, "salt")

        # Restored as nullable — original plaintext values cannot be recovered
        for col_name, col_type in columns:
            op.add_column(table, sa.Column(col_name, col_type, nullable=True))
