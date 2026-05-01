"""020 create investigational_product_log table

Revision ID: 020_investigational_product_log
Revises: 019_electronic_signatures
Create Date: 2026-04-27

WHY THIS EXISTS — DEA SCHEDULE I ACCOUNTABILITY:
  Psilocybin, LSD, ibogaine, and MDMA are all DEA Schedule I
  controlled substances. Every milligram must be accounted for
  from receipt to destruction. The DEA calls this "investigational
  product accountability" and inspectors will audit it.

  The chain of custody for a single dose looks like this:
    RECEIPT     → drug arrives at site, logged with lot number,
                  quantity, COA (certificate of analysis), stored by
    STORAGE     → drug stored in DEA-compliant vault, temp logged
    PREPARATION → pharmacist/nurse prepares dose, quantity weighed,
                  witnessed by second person
    TRANSFER    → drug moved from storage to administration room,
                  chain of custody documented
    ADMINISTRATION → dose given to participant, time, amount, who
                     administered, who witnessed
    RETURN      → unused portion returned to storage, quantity logged
    DESTRUCTION → any remaining drug destroyed per DEA protocol,
                  witnessed and documented

  Currently sessions.compound_dose records what dose was planned.
  This table records what actually happened to the physical substance.

WHY WITNESSED_BY IS NOT OPTIONAL:
  DEA requires a second person to witness preparation and destruction
  of Schedule I substances. A witnessed_by column that allows NULL
  would let the application skip this requirement. The CHECK
  constraint on event_type ensures witness is required for
  preparation and destruction events at the application layer.
  (Database-level enforcement added in Phase 4 via trigger.)

LOT_NUMBER AND COA_REFERENCE:
  The certificate of analysis (COA) from the manufacturer proves
  the substance is what it claims to be at the specified purity.
  For an IND, the FDA requires this documentation. lot_number
  ties each dose to a specific manufacturing batch with a
  specific COA.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "020_investigational_product_log"
down_revision: Union[str, None] = "019_electronic_signatures"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE investigational_product_log (
            id                  BIGSERIAL   PRIMARY KEY,
            session_id          TEXT,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            compound            TEXT        NOT NULL,
            lot_number          TEXT        NOT NULL,
            coa_reference       TEXT,
            event_type          TEXT        NOT NULL
                                CHECK (event_type IN (
                                    'receipt',
                                    'storage_check',
                                    'preparation',
                                    'transfer',
                                    'administration',
                                    'return',
                                    'destruction',
                                    'reconciliation'
                                )),
            quantity_mg         DOUBLE PRECISION,
            quantity_unit       TEXT,
            quantity_remaining_mg DOUBLE PRECISION,
            performed_by        TEXT        NOT NULL,
            witnessed_by        TEXT,
            storage_location    TEXT,
            temperature_c       DOUBLE PRECISION,
            notes               TEXT,
            event_timestamp     TIMESTAMPTZ NOT NULL,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("REVOKE UPDATE, DELETE ON investigational_product_log FROM PUBLIC;")

    op.execute("""
        CREATE INDEX idx_ip_log_session
        ON investigational_product_log (session_id);
    """)

    op.execute("""
        CREATE INDEX idx_ip_log_compound_lot
        ON investigational_product_log (compound, lot_number);
    """)

    op.execute("""
        CREATE INDEX idx_ip_log_tenancy
        ON investigational_product_log (site_id, sponsor_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS investigational_product_log;")
