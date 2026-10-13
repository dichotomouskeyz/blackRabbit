---
name: phase-5b-arc-batch
description: Use for Phase 5b ARC batch work: ECHO/APEX alignment, convergence windows, event composite profiles, and agentic interpretation over deterministic outputs.
---

# Phase 5b ARC Batch Agent

You own Agentic Response Convergence batch processing.

## Mission

Run deterministic post-session ARC over complete ECHO and APEX records, then
produce durable convergence artifacts that can be reviewed or interpreted.

## Scope

In scope:
- ECHO anchor filtering and clustering
- APEX window queries for W1/W2/W3
- baseline comparisons using persisted baseline records
- convergence density and temporal alignment outputs
- `event_composite_profiles` and session-level ARC summaries
- agentic interpretation over deterministic ARC outputs

Out of scope:
- live convergence events during capture
- mutation of raw APEX/ECHO rows
- replacing XDF reconciliation
- broad frontend/API work
- heavyweight external feature stacks unless explicitly reintroduced

## Implementation Rules

- ARC runs after session close and validation.
- Raw APEX/ECHO tables are inputs only.
- Every generated artifact must carry enough config and algorithm provenance to
  reproduce the result.
- Missing signals should be explicit in the output contract, not silently treated
  as zero response.
- Keep ARC package imports stable under `batch.arc.*`.

## Expected Tests

- anchor filtering keeps and rejects the right ECHO event classes
- W1/W2/W3 windows query the expected timestamp ranges
- missing or sparse signals are represented as unavailable
- convergence outputs are deterministic for fixed inputs
- session-close can import and invoke the ARC processor without collection errors
