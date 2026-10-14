"""Tenant-scoped immutable input loading and durable analysis persistence."""

from __future__ import annotations

import hashlib
import json

from psycopg2 import sql
from psycopg2.extras import Json

from batch.arc.features import Sample

TABLES = {
    "eeg": ("eeg_samples", "voltage", "channel_id", "NULL::float"),
    "hrv": ("hrv_samples", "rr_interval_ms", "''", "NULL::float"),
    "eda": ("eda_samples", "conductance_us", "''", "NULL::float"),
    "respiration": ("respiration_samples", "processed_amplitude", "''", "breaths_per_min"),
}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def require_verified_session(conn, session_id: str, sponsor_id: str, site_id: str) -> dict:
    if not session_id or not sponsor_id or not site_id:
        raise ValueError("session_id, sponsor_id and site_id are required")
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", (session_id,))
        if not cur.fetchone()[0]:
            raise RuntimeError("session is busy with capture, close or reconciliation")
        cur.execute(
            """SELECT participant_id, status::text FROM sessions
            WHERE id=%s AND sponsor_id=%s AND site_id=%s FOR SHARE""",
            (session_id, sponsor_id, site_id),
        )
        row = cur.fetchone()
        if not row or row[1] != "closed":
            raise RuntimeError("ARC requires a closed session under the requested tenant")
        cur.execute(
            """SELECT EXISTS(SELECT 1 FROM audit_events
            WHERE session_id=%s AND event_type='watermark_verified')""",
            (session_id,),
        )
        if not cur.fetchone()[0]:
            raise RuntimeError("ARC requires watermark_verified")
    return dict(
        session_id=session_id, participant_id=str(row[0]), sponsor_id=sponsor_id, site_id=site_id
    )


def load_inputs(conn, identity: dict) -> tuple[dict, dict, list, str]:
    params = (identity["session_id"], identity["sponsor_id"], identity["site_id"])
    digest = hashlib.sha256()
    data = {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT modality, sampling_frequency, sample_rate_hz,
                   respiration_unit, eeg_channel_names
            FROM session_signal_metadata WHERE session_id=%s AND sponsor_id=%s AND site_id=%s
            ORDER BY modality""",
            params,
        )
        metadata = {
            str(r[0]): {
                "sampling_frequency": r[1],
                "sample_rate_hz": r[2],
                "respiration_unit": r[3],
            }
            for r in cur.fetchall()
        }
        digest.update(canonical_json(metadata).encode())
        for modality, (table, value, channel, rate) in TABLES.items():
            # All identifiers and expressions are literal entries in TABLES.
            query = sql.SQL("""SELECT lsl_timestamp, {value}, sqi_flag, {channel}, {rate}
                FROM {table} WHERE session_id=%s AND sponsor_id=%s AND site_id=%s
                ORDER BY lsl_timestamp, sample_index, 4""").format(
                table=sql.Identifier(table),
                value=sql.SQL(value),
                channel=sql.SQL(channel),
                rate=sql.SQL(rate),
            )
            cur.execute(query, params)
            samples = []
            while rows := cur.fetchmany(4096):
                for r in rows:
                    sample = Sample(
                        float(r[0]),
                        float(r[1]),
                        bool(r[2]),
                        str(r[3]),
                        None if r[4] is None else float(r[4]),
                    )
                    # repr also fingerprints nonfinite input, later excluded by quality gates.
                    digest.update(repr((modality, r)).encode())
                    samples.append(sample)
            data[modality] = samples
        cur.execute(
            """SELECT id, alert_type, severity, message, algorithm_name,
                       algorithm_version, algorithm_parameters, lsl_timestamp
            FROM alert_events WHERE session_id=%s AND sponsor_id=%s AND site_id=%s
            AND alert_type::text='safety' ORDER BY lsl_timestamp, id""",
            params,
        )
        safety = [
            dict(
                zip(
                    (
                        "id",
                        "alert_type",
                        "severity",
                        "message",
                        "algorithm_name",
                        "algorithm_version",
                        "algorithm_parameters",
                        "lsl_timestamp",
                    ),
                    (str(r[0]), *r[1:]),
                )
            )
            for r in cur.fetchall()
        ]
        digest.update(canonical_json(safety).encode())
    return data, metadata, safety, digest.hexdigest()


def persist_analysis(conn, artifact: dict, baselines: list[dict], ecps: list[dict]) -> None:
    identity = artifact["identity"]
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO analysis_runs
            (id, session_id, participant_id, sponsor_id, site_id, config_sha256,
             input_sha256, algorithm_version, artifact_sha256, artifact)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO NOTHING""",
            (
                artifact["analysis_id"],
                identity["session_id"],
                identity["participant_id"],
                identity["sponsor_id"],
                identity["site_id"],
                artifact["config_sha256"],
                artifact["input_sha256"],
                artifact["algorithm_version"],
                hashlib.sha256(canonical_json(artifact).encode()).hexdigest(),
                Json(artifact),
            ),
        )
        for baseline in baselines:
            row = {**identity, **baseline, "analysis_id": artifact["analysis_id"]}
            columns = list(row)
            cur.execute(
                sql.SQL(
                    "INSERT INTO session_baselines ({}) VALUES ({}) "
                    "ON CONFLICT (analysis_id, modality, signal_component) DO NOTHING"
                ).format(
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns),
                ),
                [row[key] for key in columns],
            )
        for ecp in ecps:
            row = {**ecp, "analysis_id": artifact["analysis_id"]}
            columns = list(row)
            cur.execute(
                sql.SQL(
                    "INSERT INTO event_composite_profiles ({}) VALUES ({}) "
                    "ON CONFLICT (analysis_id, echo_event_id) DO NOTHING"
                ).format(
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns),
                ),
                [Json(row[k]) if isinstance(row[k], (dict, list)) else row[k] for k in columns],
            )


def load_analysis(conn, analysis_id: str, sponsor_id: str, site_id: str) -> dict | None:
    if not sponsor_id or not site_id:
        raise ValueError("sponsor_id and site_id are required")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT artifact FROM analysis_runs WHERE id=%s AND sponsor_id=%s AND site_id=%s",
            (analysis_id, sponsor_id, site_id),
        )
        row = cur.fetchone()
    return row[0] if row else None
