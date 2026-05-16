"""Biosignal integrity log writes."""

import hashlib

from capture.logger import get_logger

log = get_logger("lsl_forwarder")


def write_integrity_log(thread, conn, rows: list[dict]) -> None:
    try:
        sorted_rows = sorted(
            rows, key=lambda row: tuple(row[key] for key in thread._hash_sort_keys)
        )
        hash_input = ",".join(
            "|".join(str(row[field]) for field in thread._hash_fields) for row in sorted_rows
        )
        chunk_hash = hashlib.md5(hash_input.encode(), usedforsecurity=False).hexdigest()
        sample_indices = [row["sample_index"] for row in rows]
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO biosignal_integrity_log
               (session_id, site_id, sponsor_id, table_name, row_count,
                min_sample_index, max_sample_index, chunk_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                rows[0]["session_id"],
                rows[0]["site_id"],
                rows[0]["sponsor_id"],
                thread._table_name,
                len(rows),
                min(sample_indices),
                max(sample_indices),
                chunk_hash,
            ),
        )
        conn.commit()
        cur.close()
    except Exception as exc:
        log.warning(
            f"{thread._stream_type} integrity log write failed",
            extra={"error": str(exc)},
        )
        try:
            conn.rollback()
        except Exception as rb_exc:
            log.debug(
                f"{thread._stream_type} DB rollback failed after integrity log write error",
                extra={"error": str(rb_exc)},
            )
