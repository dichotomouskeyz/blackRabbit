# Future DB Health Upgrades

## Status

Deferred. This document records a possible post-MVP resilience improvement. It
does not change the current capture, reconciliation, or database workflow.

## Append-Only Recovery Journal

Consider adding a local, append-only recovery journal alongside the existing XDF
and PostgreSQL writes. Its purpose would be forensic inspection and additional
redundancy when live database writes fail.

The intended ECHO write order would be:

1. Write the raw marker to XDF.
2. Append the event to the recovery journal.
3. Attempt the normal PostgreSQL insert into `echo_events`.

The journal should not replace XDF, PostgreSQL, the in-memory ECHO buffer, or XDF
reconciliation.

## Suggested Storage

Use a local SQLite database rather than a custom binary file. SQLite provides
indexing, transaction boundaries, corruption handling, and direct query support
without requiring a new binary query format.

Each journal record should include:

- a monotonically increasing sequence number;
- pseudonymous session, participant, site, and sponsor identifiers;
- the original LSL timestamp;
- event type and ECHO actor context;
- a byte-packed copy of the event payload;
- a payload format version;
- a checksum for corruption detection;
- the local journal insertion time.

Typed columns would support ordinary filtering while the packed payload would
preserve the exact journal representation.

## Query and Recovery Model

The journal should be forensic-only. It must not automatically insert missing
records into PostgreSQL or become part of normal application reads.

Explicit inspection tooling should compare journal records with `echo_events`
and report:

- records present in both stores;
- records present in the journal but missing from PostgreSQL;
- duplicate or conflicting records;
- checksum or sequence discontinuities.

Any replay into PostgreSQL should remain an explicit operator action with a
preview, tenancy validation, idempotency checks, and an auditable result.

## Failure Coverage

This journal would preserve a queryable local record when:

- PostgreSQL is temporarily unavailable;
- repeated live writes and buffer flushes fail;
- the in-memory ECHO buffer reaches its maximum size;
- the capture process exits before buffered rows reach PostgreSQL.

It would not protect against loss of the host or storage device when XDF,
SQLite, and PostgreSQL data all reside on the same machine.

## Required Invariants

Any future implementation must:

- continue writing XDF before database-oriented paths;
- preserve separate `lsl_timestamp` and journal insertion time values;
- preserve raw ECHO records and replayability;
- use pseudonymous identifiers;
- enforce sponsor and site tenancy during queries and replay;
- avoid direct writes to `audit_events`;
- keep the journal append-only;
- keep PostgreSQL as the canonical query store;
- prevent journal data from being treated as verified session data;
- require successful reconciliation before `watermark_verified`.

## Deferred Questions

Before implementation, decide:

- whether the journal covers only ECHO or all APEX streams;
- the packed payload format and versioning rules;
- journal rotation, retention, and disk-capacity limits;
- encryption and local key management;
- how operator inspection and approved replay are exposed;
- whether journal health should block session close.
