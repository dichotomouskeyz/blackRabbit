"""Biosignal integrity log writes."""

import hashlib
import json

HASH_METHOD = "md5"


def chunk_hash(thread, rows: list[dict]) -> str:
    sorted_rows = sorted(rows, key=lambda row: tuple(row[key] for key in thread.hash_sort_keys))
    hash_input = json.dumps(
        [{field: row[field] for field in thread.hash_fields} for row in sorted_rows],
        sort_keys=True,
    )
    return hashlib.md5(hash_input.encode(), usedforsecurity=False).hexdigest()


def write_integrity_log(thread, cur, rows: list[dict]) -> None:
    """Write the integrity row using the caller's open transaction.

    No-ops for threads without integrity config (no table_name) — every real
    biosignal StreamThread declares one.
    """
    if getattr(thread, "table_name", None) is None:
        return
    sample_indices = [row["sample_index"] for row in rows]
    cur.execute(
        """INSERT INTO biosignal_integrity_log
           (session_id, participant_id, site_id, sponsor_id, log_type, table_name,
            row_count, min_sample_index, max_sample_index, chunk_hash, hash_method)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            rows[0]["session_id"],
            rows[0]["participant_id"],
            rows[0]["site_id"],
            rows[0]["sponsor_id"],
            "chunk_integrity",
            thread.table_name,
            len(rows),
            min(sample_indices),
            max(sample_indices),
            chunk_hash(thread, rows),
            HASH_METHOD,
        ),
    )
