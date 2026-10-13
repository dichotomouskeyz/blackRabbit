"""003 create compound_reference table

Revision ID: 003_compound_reference
Revises: 002_sessions
Create Date: 2026-05-03

WHY A SEPARATE REFERENCE TABLE:
  sessions.compound is a TEXT column that identifies the investigational
  compound administered in a session. Without a reference table, that
  column is free-text — "LSD", "lsd", "Lsd", and "lysergic acid
  diethylamide" could all appear in different rows for the same substance.
  That makes downstream analysis brittle and difficult to reproduce.

  This table defines the closed vocabulary. sessions.compound must be
  one of the compound_id values here. display_name gives a human-readable
  label; iupac_name is the authoritative chemical identity; cas_number is
  the globally unique registry identifier commonly used by regulated
  deployments and chemical reference material.

WHY IUPAC AND CAS BOTH:
  IUPAC names are unambiguous: no two valid IUPAC names can refer to the
  same compound. CAS numbers are globally unique identifiers issued by the
  Chemical Abstracts Service. Keeping both supports deployments that need
  formal chemical accountability without making the open-source core a
  compliance product.

WHY PSILOCIN IS INCLUDED:
  Psilocybin ([3-[2-(dimethylamino)ethyl]-1H-indol-4-yl] dihydrogen
  phosphate) is a prodrug that dephosphorylates in vivo to psilocin
  (3-[2-(dimethylamino)ethyl]-1H-indol-4-ol), the pharmacologically
  active form. Some protocols measure psilocin plasma concentration
  directly. Including both lets the analytics layer distinguish between
  the administered compound and its active metabolite.

WHY IBOGAINE AND IBOGAINE HYDROCHLORIDE ARE SEPARATE ROWS:
  Free base and hydrochloride salt are chemically distinct with separate
  CAS numbers. The two forms have different molecular weights, so the same
  molar dose corresponds to different administered masses. Conflating them would
  introduce a systematic error in dose accountability records.

SEED DATA:
  Populated at migration time via INSERT. The default vocabulary covers the
  compounds this project models in local research and demo sessions.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "003_compound_reference"
down_revision: Union[str, None] = "002_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE compound_reference (
            compound_id     TEXT    PRIMARY KEY,
            display_name    TEXT    NOT NULL,
            iupac_name      TEXT    NOT NULL,
            cas_number      TEXT    NOT NULL UNIQUE,
            notes           TEXT
        );
    """)

    op.execute("""
        INSERT INTO compound_reference
            (compound_id, display_name, iupac_name, cas_number, notes)
        VALUES
            (
                'lsd',
                'LSD',
                '(6aR,9R)-N,N-diethyl-7-methyl-4,6,6a,7,8,9-hexahydroindolo[4,3-fg]quinoline-9-carboxamide',
                '50-37-3',
                'Lysergic acid diethylamide. DEA Schedule I. Common synonym: lysergide.'
            ),
            (
                'psilocybin',
                'Psilocybin',
                '[3-[2-(dimethylamino)ethyl]-1H-indol-4-yl] dihydrogen phosphate',
                '520-52-5',
                'Prodrug; dephosphorylates in vivo to psilocin. '
                'Alternative name: 4-phosphoryloxy-N,N-dimethyltryptamine. DEA Schedule I.'
            ),
            (
                'psilocin',
                'Psilocin',
                '3-[2-(dimethylamino)ethyl]-1H-indol-4-ol',
                '520-53-6',
                'Active metabolite of psilocybin. '
                'Alternative name: 4-hydroxy-N,N-dimethyltryptamine (4-OH-DMT). DEA Schedule I.'
            ),
            (
                'dmt',
                'DMT',
                '2-(1H-indol-3-yl)-N,N-dimethylethan-1-amine',
                '61-50-7',
                'N,N-Dimethyltryptamine. DEA Schedule I.'
            ),
            (
                '5meo_dmt',
                '5-MeO-DMT',
                '2-(5-methoxy-1H-indol-3-yl)-N,N-dimethylethan-1-amine',
                '1019-45-0',
                '5-Methoxy-N,N-dimethyltryptamine. DEA Schedule I.'
            ),
            (
                'ibogaine',
                'Ibogaine',
                '(1R,9S,10S,16R)-10-ethyl-4-methoxy-17-azatetracyclo[7.6.1.02,7.09,16]heptadeca-2,4,6,13-tetraene',
                '83-74-9',
                'Free base form. DEA Schedule I. See also ibogaine_hcl for the hydrochloride salt.'
            ),
            (
                'ibogaine_hcl',
                'Ibogaine Hydrochloride',
                '(1R,9S,10S,16R)-10-ethyl-4-methoxy-17-azatetracyclo[7.6.1.02,7.09,16]heptadeca-2,4,6,13-tetraene hydrochloride',
                '4395-90-8',
                'Hydrochloride salt; the form most commonly used in clinical administration. '
                'Different molecular weight from free base — dose accountability must specify which form.'
            ),
            (
                'mdma',
                'MDMA',
                '1-(1,3-benzodioxol-5-yl)-N-methylpropan-2-amine',
                '42542-10-9',
                '3,4-Methylenedioxymethamphetamine, racemic free base. DEA Schedule I. '
                'Used in MAPS-sponsored PTSD trials.'
            );
    """)

    # sessions is created in 002 before compound_reference exists, so the FK
    # must be added here after the reference table and its seed data are in place.
    op.execute("""
        ALTER TABLE sessions
        ADD CONSTRAINT fk_sessions_compound
        FOREIGN KEY (compound) REFERENCES compound_reference(compound_id);
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP CONSTRAINT IF EXISTS fk_sessions_compound;")
    op.execute("DROP TABLE IF EXISTS compound_reference;")
