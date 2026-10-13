"""Bounded, tenant-scoped recording reads with server-issued evidence.

This module has no model SDK dependency. Saved ARC output is never recomputed.
"""

from __future__ import annotations

import copy
import hashlib
import math
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Callable
from uuid import UUID

import numpy as np
import psycopg2
from psycopg2 import sql

from api.arc import SessionNotFound, WatermarkNotVerified, assert_session_arc_ready
from batch.arc.features import COMPONENTS, Sample, feature_series
from batch.arc.storage import TABLES, canonical_json
from investigation.models import Evidence, InvestigationError

MAX_ROWS = 1_000_000
MAX_WINDOW_SECONDS = 600
MAX_CHART_POINTS = 2000
QUERY_TIMEOUT_MS = 5000
CONNECT_TIMEOUT_SECONDS = 5
COMPUTE_TIMEOUT_SECONDS = 12
MAX_QUALITY_EVENT_DETAILS = 20

SCOPE_SQL = "session_id=%(session_id)s AND sponsor_id=%(sponsor_id)s AND site_id=%(site_id)s"


def _bounded_time(start: float) -> None:
    if time.monotonic() - start > COMPUTE_TIMEOUT_SECONDS:
        raise InvestigationError("computation_timeout", "Signal inspection exceeded its budget.")


def _bounded_readonly_connection():
    """Apply a connection bound independently of configured SQL timeouts."""
    from api.deps import _readonly_url

    # Explicit kwargs override any DSN timeout. The API's canonical resolver
    # still enforces the dedicated SELECT-only URL with no write-role fallback.
    return psycopg2.connect(_readonly_url(), connect_timeout=CONNECT_TIMEOUT_SECONDS)


class RecordingTools:
    """One selected recording and immutable saved report, shared across turns."""

    def __init__(
        self,
        session_id: str,
        sponsor_id: str,
        site_id: str,
        connect: Callable | None = None,
    ) -> None:
        try:
            self.session_id, self.sponsor_id, self.site_id = (
                str(UUID(value)) for value in (session_id, sponsor_id, site_id)
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise InvestigationError(
                "invalid_identity", "Valid server identity is required.", 422
            ) from exc
        if connect is None:
            connect = _bounded_readonly_connection
        self._connect = connect
        self.scope = dict(
            session_id=self.session_id, sponsor_id=self.sponsor_id, site_id=self.site_id
        )
        self.evidence: dict[str, Evidence] = {}
        self.charts: list[dict] = []
        self.trace: list[dict] = []
        with self._connection() as conn:
            self._assert_ready(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id::text, artifact_sha256, CASE WHEN octet_length(artifact::text) "
                    "<= 8388608 THEN artifact ELSE NULL END FROM analysis_runs WHERE "
                    + SCOPE_SQL
                    + " ORDER BY created_at DESC, id DESC LIMIT 1",
                    self.scope,
                )
                row = cur.fetchone()
                if row is None:
                    raise InvestigationError(
                        "analysis_unavailable", "No saved ARC analysis exists.", 404
                    )
                self.analysis_id, self.artifact_sha256 = str(row[0]), row[1]
                if row[2] is None:
                    raise InvestigationError(
                        "artifact_limit", "Saved report exceeds the inspection limit."
                    )
                self._artifact = copy.deepcopy(row[2])
                digest = hashlib.sha256(canonical_json(self._artifact).encode()).hexdigest()
                if digest != self.artifact_sha256:
                    raise InvestigationError(
                        "analysis_integrity", "Saved ARC artifact hash does not match."
                    )
                identity = self._artifact.get("identity", {})
                if any(identity.get(key) != value for key, value in self.scope.items()):
                    raise InvestigationError(
                        "analysis_integrity", "Saved ARC identity does not match."
                    )
                cur.execute(
                    "SELECT capture_source FROM sessions WHERE id=%(session_id)s "
                    "AND sponsor_id=%(sponsor_id)s AND site_id=%(site_id)s",
                    self.scope,
                )
                self.capture_source = cur.fetchone()[0]
                cur.execute(
                    "SELECT modality, sample_rate_hz, sampling_frequency, "
                    "eeg_channel_names, respiration_unit FROM session_signal_metadata WHERE "
                    + SCOPE_SQL
                    + " ORDER BY modality LIMIT 65",
                    self.scope,
                )
                rows = cur.fetchall()
                if len(rows) > 64:
                    raise InvestigationError("metadata_limit", "Too many signal metadata records.")
                self._metadata: dict[str, dict[str, Any]] = {
                    r[0]: dict(
                        sample_rate_hz=r[1] or r[2],
                        eeg_channel_names=r[3] or [],
                        respiration_unit=r[4],
                    )
                    for r in rows
                }

    @contextmanager
    def _connection(self):
        conn = None
        try:
            conn = self._connect()
            conn.set_session(readonly=True, isolation_level="REPEATABLE READ", autocommit=False)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('statement_timeout', %s, true)", (str(QUERY_TIMEOUT_MS),)
                )
            yield conn
        except psycopg2.errors.QueryCanceled as exc:
            raise InvestigationError(
                "query_timeout", "Recording query exceeded its budget."
            ) from exc
        except psycopg2.Error as exc:
            raise InvestigationError(
                "database_unavailable", "Recording query failed.", 503
            ) from exc
        finally:
            if conn is not None:
                try:
                    conn.rollback()
                finally:
                    conn.close()

    def _assert_ready(self, conn) -> None:
        try:
            assert_session_arc_ready(conn, self.session_id, self.sponsor_id, self.site_id)
        except SessionNotFound as exc:
            raise InvestigationError(
                "session_not_found", "Recording is unavailable for this tenant.", 404
            ) from exc
        except WatermarkNotVerified as exc:
            raise InvestigationError(
                "capture_unverified", "Recording must be closed and watermark-verified."
            ) from exc

    def _record(
        self,
        metric,
        value,
        *,
        source="saved_arc",
        units=None,
        event_id=None,
        window=None,
        modality=None,
        session_id=None,
        analysis_id=None,
        artifact_sha256=None,
    ):
        fields = dict(
            session_id=session_id or self.session_id,
            analysis_id=self.analysis_id if analysis_id is None else analysis_id,
            artifact_sha256=self.artifact_sha256 if artifact_sha256 is None else artifact_sha256,
            source=source,
            metric=metric,
            value=value,
            units=units,
            event_id=event_id,
            window=window,
            modality=modality,
        )
        evidence_id = "ev_" + hashlib.sha256(canonical_json(fields).encode()).hexdigest()[:24]
        if evidence_id not in self.evidence and len(self.evidence) >= 10000:
            raise InvestigationError(
                "evidence_limit", "Start a new investigation to collect more evidence."
            )
        self.evidence[evidence_id] = Evidence.model_validate({"id": evidence_id, **fields})
        return evidence_id

    def _finish(self, name, payload, arguments=None):
        payload["evidence_refs"] = {
            ref: {
                key: getattr(self.evidence[ref], key)
                for key in ("metric", "window", "modality", "event_id")
                if getattr(self.evidence[ref], key) is not None
            }
            for ref in payload["evidence_ids"]
        }
        self.trace.append(
            dict(tool=name, arguments=arguments or {}, evidence_ids=payload["evidence_ids"])
        )
        del self.trace[:-100]
        return payload

    def list_sessions(self) -> dict:
        """List up to 50 recordings visible to the server's sponsor and site."""
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT s.id::text, s.status::text, s.capture_source, "
                "EXISTS(SELECT 1 FROM analysis_runs a WHERE a.session_id=s.id "
                "AND a.sponsor_id=s.sponsor_id AND a.site_id=s.site_id) "
                "FROM sessions s WHERE s.sponsor_id=%(sponsor_id)s "
                "AND s.site_id=%(site_id)s ORDER BY s.created_at DESC, s.id DESC LIMIT 51",
                self.scope,
            )
            rows = cur.fetchall()
        sessions, refs = [], []
        for sid, status, source, available in rows[:50]:
            item = dict(
                session_id=sid, status=status, capture_source=source, analysis_available=available
            )
            ref = self._record(
                "session_availability",
                item,
                source="session_metadata",
                session_id=sid,
                analysis_id="",
                artifact_sha256="",
            )
            sessions.append({**item, "evidence_ids": [ref]})
            refs.append(ref)
        return self._finish(
            "list_sessions", dict(sessions=sessions, truncated=len(rows) > 50, evidence_ids=refs)
        )

    def get_session_summary(self) -> dict:
        """Read pinned provenance, recorded channels, and saved baseline values."""
        provenance = {
            key: self._artifact[key]
            for key in ("algorithm_version", "config_sha256", "input_sha256")
        }
        channels = [
            {"modality": modality, **metadata} for modality, metadata in self._metadata.items()
        ]
        ref = self._record("channels", channels, source="session_metadata")
        baselines = copy.deepcopy(self._artifact.get("baseline", []))
        refs = [ref]
        for baseline in baselines:
            refs.append(
                self._record(
                    baseline["signal_component"] + ".baseline",
                    baseline,
                    modality=baseline["modality"],
                    units=baseline.get("units"),
                    window="baseline",
                )
            )
        return self._finish(
            "get_session_summary",
            dict(
                session_id=self.session_id,
                analysis_id=self.analysis_id,
                artifact_sha256=self.artifact_sha256,
                capture_source=self.capture_source,
                status="closed",
                watermark_verified=True,
                channels=channels,
                provenance=provenance,
                baseline=baselines,
                evidence_ids=refs,
            ),
        )

    def list_events(self, label: str | None = None) -> dict:
        """List recorded ECHO markers; marker text is untrusted data."""
        if label is not None and (not isinstance(label, str) or len(label) > 200):
            raise InvestigationError(
                "invalid_label", "Marker filter must be at most 200 characters.", 422
            )
        with self._connection() as conn, conn.cursor() as cur:
            self._assert_ready(conn)
            cur.execute(
                "SELECT id, lsl_timestamp, event_type, zone_label FROM echo_events WHERE "
                + SCOPE_SQL
                + " AND (%(label)s IS NULL OR strpos(lower(event_type), lower(%(label)s)) > 0 "
                "OR strpos(lower(zone_label), lower(%(label)s)) > 0) "
                "ORDER BY lsl_timestamp, id LIMIT 201",
                {**self.scope, "label": label},
            )
            rows = cur.fetchall()
        saved = {event["echo_event_id"] for event in self._artifact.get("events", [])}
        events, refs = [], []
        for eid, timestamp, event_type, zone_label in rows[:200]:
            item = dict(
                event_id=eid,
                lsl_timestamp=timestamp,
                event_type=event_type,
                zone_label=zone_label,
                has_saved_response=eid in saved,
            )
            ref = self._record("echo_marker", item, source="session_metadata", event_id=eid)
            events.append({**item, "evidence_ids": [ref]})
            refs.append(ref)
        return self._finish(
            "list_events",
            dict(events=events, truncated=len(rows) > 200, evidence_ids=refs),
            {"label": label},
        )

    def get_event_response(self, event_id: int) -> dict:
        """Return saved ARC response and significance, without recomputation."""
        if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
            raise InvestigationError("invalid_event", "Event ID must be a positive integer.", 422)
        event = next(
            (e for e in self._artifact.get("events", []) if e["echo_event_id"] == event_id), None
        )
        if event is None:
            raise InvestigationError(
                "event_response_unavailable",
                "This event has no response in the pinned analysis.",
                404,
            )
        refs = [
            self._record(metric, value, event_id=event_id)
            for metric, value in event.items()
            if metric != "windows"
        ]
        for name, window in event["windows"].items():
            for metric, value in window.items():
                if metric != "metrics":
                    refs.append(self._record(metric, value, event_id=event_id, window=name))
                    continue
                for component, measurements in value.items():
                    for key, measurement in measurements.items():
                        refs.append(
                            self._record(
                                component + "." + key,
                                measurement,
                                event_id=event_id,
                                window=name,
                                modality=component.split(".")[0],
                                units=measurements.get("units")
                                if key in ("observed_value", "baseline_mean", "baseline_std")
                                else None,
                            )
                        )
        return self._finish(
            "get_event_response",
            dict(
                event_id=event_id,
                analysis_id=self.analysis_id,
                source="saved_arc",
                response=copy.deepcopy(event),
                evidence_ids=refs,
            ),
            {"event_id": event_id},
        )

    def get_recording_quality(self) -> dict:
        """Read saved exclusions and quality counts; this is not clinical quality grading."""
        summary = copy.deepcopy(self._artifact.get("quality_summary", {}))
        refs = [
            self._record(metric, value, source="recording_quality", modality=modality)
            for modality, metrics in summary.items()
            for metric, value in metrics.items()
        ]
        unavailable = copy.deepcopy(self._artifact.get("unavailable_signals", {}))
        refs.append(self._record("unavailable_signals", unavailable, source="recording_quality"))
        events = self._artifact.get("events", [])
        counts = {
            "event_count": len(events),
            "testable_event_count": sum(bool(event["testable"]) for event in events),
            "untestable_event_count": sum(not event["testable"] for event in events),
            "window_count": sum(len(event["windows"]) for event in events),
            "ineligible_window_count": sum(
                not window["eligible"] for event in events for window in event["windows"].values()
            ),
            "excluded_signal_window_count": sum(
                len(window.get("excluded_signals", {}))
                for event in events
                for window in event["windows"].values()
            ),
            "returned_event_count": min(len(events), MAX_QUALITY_EVENT_DETAILS),
            "omitted_event_count": max(0, len(events) - MAX_QUALITY_EVENT_DETAILS),
        }
        refs.append(self._record("event_exclusion_counts", counts, source="recording_quality"))
        exclusions = [
            dict(
                event_id=e["echo_event_id"],
                testable=e["testable"],
                test_exclusion_reason=e.get("test_exclusion_reason"),
                windows={
                    name: dict(
                        eligible=w["eligible"],
                        exclusion_reason=w.get("exclusion_reason"),
                        excluded_signals=copy.deepcopy(w.get("excluded_signals", {})),
                    )
                    for name, w in e["windows"].items()
                },
            )
            for e in events[:MAX_QUALITY_EVENT_DETAILS]
        ]
        refs.append(self._record("event_exclusions", exclusions, source="recording_quality"))
        return self._finish(
            "get_recording_quality",
            dict(
                quality_summary=summary,
                unavailable_signals=unavailable,
                event_exclusions=exclusions,
                event_exclusion_counts=counts,
                event_exclusions_truncated=len(events) > MAX_QUALITY_EVENT_DETAILS,
                limitations=self._artifact.get("limitations", []),
                evidence_ids=refs,
            ),
        )

    def inspect_signal_window(
        self,
        modality: str,
        start_lsl_timestamp: float,
        end_lsl_timestamp: float,
        channel: str | None = None,
    ) -> dict:
        """Compute bounded exploratory statistics, emitting charts outside model context."""
        if modality not in TABLES:
            raise InvestigationError("invalid_modality", "Use eeg, hrv, eda, or respiration.", 422)
        if any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in (start_lsl_timestamp, end_lsl_timestamp)
        ):
            raise InvestigationError("invalid_window", "Window bounds must be finite numbers.", 422)
        duration = end_lsl_timestamp - start_lsl_timestamp
        if not 0 < duration <= MAX_WINDOW_SECONDS:
            raise InvestigationError(
                "invalid_window", "Window must be positive and at most 600 seconds.", 422
            )
        metadata = self._metadata.get(modality)
        if metadata is None:
            raise InvestigationError("signal_unavailable", "Signal metadata is unavailable.", 404)
        if channel is not None and (
            modality != "eeg" or channel not in metadata["eeg_channel_names"]
        ):
            raise InvestigationError(
                "invalid_channel", "Channel is not present in this recording.", 422
            )
        declared_channels = metadata["eeg_channel_names"] if modality == "eeg" else []
        if modality == "eeg" and (
            not isinstance(declared_channels, list)
            or not declared_channels
            or not all(isinstance(name, str) and name for name in declared_channels)
            or len(set(declared_channels)) != len(declared_channels)
        ):
            raise InvestigationError(
                "invalid_metadata", "EEG requires declared recording channels."
            )
        expected_channels = (channel,) if channel is not None else tuple(declared_channels)
        if len(expected_channels) > 64:
            raise InvestigationError(
                "channel_limit", "Select one channel for recordings over 64 channels.", 422
            )
        raw_epoch = self._artifact.get("config", {}).get("features", {}).get("epoch_s", 10)
        if (
            isinstance(raw_epoch, bool)
            or not isinstance(raw_epoch, (int, float))
            or not math.isfinite(raw_epoch)
            or raw_epoch < 1
            or math.floor(duration / raw_epoch + 1e-8) > 600
        ):
            raise InvestigationError(
                "invalid_epoch_config",
                "Inspection requires epochs of at least one second and at most 600 epochs.",
                422,
            )
        epoch_s = float(raw_epoch)
        table, value, channel_expression, rate = TABLES[modality]
        query = sql.SQL(
            "SELECT lsl_timestamp, {value}, sqi_flag, {channel}, {rate} FROM {table} WHERE "
            + SCOPE_SQL
            + " AND lsl_timestamp >= %(start)s AND lsl_timestamp < %(end)s "
            "AND (%(channel)s IS NULL OR {channel}=%(channel)s) "
            "ORDER BY lsl_timestamp, sample_index, 4 LIMIT %(limit)s"
        ).format(
            value=sql.SQL(value),
            channel=sql.SQL(channel_expression),
            rate=sql.SQL(rate),
            table=sql.Identifier(table),
        )
        params = {
            **self.scope,
            "start": start_lsl_timestamp,
            "end": end_lsl_timestamp,
            "channel": channel,
            "limit": MAX_ROWS + 1,
        }
        with self._connection() as conn, conn.cursor() as cur:
            self._assert_ready(conn)
            cur.execute(query, params)
            rows = cur.fetchall()
        if len(rows) > MAX_ROWS:
            raise InvestigationError(
                "row_limit", "Signal window exceeds one million rows; narrow it.", 422
            )
        if not rows:
            raise InvestigationError(
                "signal_unavailable", "No signal samples exist in this window.", 404
            )
        started = time.monotonic()
        groups = defaultdict(list)
        for index, row in enumerate(rows):
            if index % 4096 == 0:
                _bounded_time(started)
            groups[str(row[3])].append(
                Sample(
                    float(row[0]),
                    float(row[1]),
                    bool(row[2]),
                    str(row[3]),
                    None if row[4] is None else float(row[4]),
                )
            )
        if len(groups) > 64 or len(self.charts) + len(groups) > 64:
            raise InvestigationError(
                "chart_limit", "Inspect fewer channels or drain existing charts.", 422
            )
        if modality == "eeg" and not set(groups).issubset(expected_channels):
            raise InvestigationError(
                "invalid_channel", "Captured EEG includes undeclared channels.", 422
            )
        missing_channels = sorted(set(expected_channels) - set(groups))
        window_id = f"lsl:[{start_lsl_timestamp:.9f},{end_lsl_timestamp:.9f})"
        statistics, pending_charts, refs = {}, [], []
        unit = {
            "eeg": "captured_voltage_unit",
            "hrv": "ms",
            "eda": "uS",
            "respiration": metadata.get("respiration_unit") or "captured_amplitude_unit",
        }[modality]
        for channel_name, samples in groups.items():
            _bounded_time(started)
            stats, points = _describe_channel(
                samples, modality, metadata.get("sample_rate_hz"), started
            )
            statistics[channel_name or modality] = stats
            for metric, measurement in stats.items():
                refs.append(
                    self._record(
                        f"{channel_name or modality}.{metric}",
                        measurement,
                        source="raw_window",
                        window=window_id,
                        modality=modality,
                        units=unit if metric in ("mean", "min", "max", "std") else None,
                    )
                )
            pending_charts.append(
                dict(
                    session_id=self.session_id,
                    analysis_id=self.analysis_id,
                    modality=modality,
                    channel=channel_name or None,
                    units=unit,
                    start_lsl_timestamp=start_lsl_timestamp,
                    end_lsl_timestamp=end_lsl_timestamp,
                    exploratory=True,
                    points=points,
                )
            )
        all_samples = [sample for samples in groups.values() for sample in samples]
        features = feature_series(
            modality,
            all_samples,
            list(COMPONENTS[modality]),
            origin=start_lsl_timestamp,
            end=end_lsl_timestamp,
            epoch_s=epoch_s,
            amplitude_unit=unit,
            expected_channels=expected_channels,
            sample_rate_hz=metadata.get("sample_rate_hz"),
            check_budget=lambda: _bounded_time(started),
        )
        feature_summary = {}
        for series in features:
            valid = [value for value in series.values if value is not None]
            mean = float(np.mean(valid)) if valid else None
            feature_summary[series.component] = dict(
                mean=mean,
                units=series.unit,
                valid_epochs=len(valid),
                total_epochs=len(series.values),
            )
            refs.append(
                self._record(
                    series.component + ".epoch_summary",
                    feature_summary[series.component],
                    source="raw_window",
                    window=window_id,
                    modality=modality,
                    units=series.unit,
                )
            )
        _bounded_time(started)
        self.charts.extend(pending_charts)
        arguments = dict(
            modality=modality,
            start_lsl_timestamp=start_lsl_timestamp,
            end_lsl_timestamp=end_lsl_timestamp,
            channel=channel,
        )
        return self._finish(
            "inspect_signal_window",
            dict(
                **arguments,
                exploratory=True,
                statistics=statistics,
                features=feature_summary,
                chart_count=len(pending_charts),
                missing_channels=missing_channels,
                evidence_ids=refs,
                limitations=[
                    "Descriptive window statistics do not recalculate saved ARC significance.",
                    "Chart bins containing flags, invalid values or gaps break the plotted line.",
                ],
            ),
            arguments,
        )


def _describe_channel(samples, modality, sample_rate_hz, started):
    """Aggregate every input flag/gap into bounded plot bins instead of losing it."""
    times = np.asarray([sample.timestamp for sample in samples])
    values = np.asarray([sample.value for sample in samples])
    flagged = np.asarray([sample.flagged for sample in samples], dtype=bool)
    valid = np.isfinite(values) & ~flagged
    if modality == "hrv":
        valid &= values > 0
    clean = values[valid]
    differences = np.diff(times)
    positive = differences[differences > 0]
    step = (
        1 / sample_rate_hz
        if sample_rate_hz and sample_rate_hz > 0
        else (float(np.median(positive)) if len(positive) else None)
    )
    gap_before = np.zeros(len(samples), dtype=bool)
    if step:
        gap_before[1:] = (differences > step * 1.8) | (differences <= 0)
    stats = dict(
        sample_count=len(samples),
        usable_sample_count=int(valid.sum()),
        flagged_sample_count=int(flagged.sum()),
        invalid_sample_count=int((~np.isfinite(values)).sum()),
        gap_count=int(gap_before.sum()),
        mean=float(np.mean(clean)) if len(clean) else None,
        min=float(np.min(clean)) if len(clean) else None,
        max=float(np.max(clean)) if len(clean) else None,
        std=float(np.std(clean)) if len(clean) else None,
        coverage_start_lsl_timestamp=float(times[0]),
        coverage_end_lsl_timestamp=float(times[-1]),
    )
    width = max(1, math.ceil(len(samples) / MAX_CHART_POINTS))
    points = []
    for first in range(0, len(samples), width):
        _bounded_time(started)
        end = min(len(samples), first + width)
        broken = bool(not np.all(valid[first:end]) or np.any(gap_before[first:end]))
        subset = values[first:end][valid[first:end]]
        points.append(
            dict(
                lsl_timestamp=float(times[first]),
                end_lsl_timestamp=float(times[end - 1]),
                value=None if broken else float(np.mean(subset)),
                minimum=float(np.min(subset)) if len(subset) else None,
                maximum=float(np.max(subset)) if len(subset) else None,
                flagged=bool(np.any(flagged[first:end])),
                gap_before=bool(np.any(gap_before[first:end])),
                sample_count=end - first,
            )
        )
    return stats, points
