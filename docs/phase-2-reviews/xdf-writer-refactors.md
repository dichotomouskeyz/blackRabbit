# XDF Writer Current State and Refactor Notes

## Current State

`capture/xdf/writer.py` owns the local XDF backup file for one capture session.
It is the durable reconciliation source used when DB writes lag, fail, or need
backfill during session close.

The current writer does several jobs:

- Opens one XDF file per session under `settings.XDF_BACKUP_DIR`.
- Writes the XDF magic bytes, file header, and stream headers at startup.
- Accepts writes from the APEX stream threads and the ECHO marker thread.
- Uses an internal `threading.Lock` so concurrent writes serialize through one
  file handle.
- Tracks per-stream sample counts plus first and last LSL timestamps.
- Writes stream footers and closes the file when capture teardown calls
  `close()`.

The public surface is intentionally small:

- `XDFWriter(session_id, participant_id, site_id, sponsor_id)`
- `write_samples(stream_name, samples, timestamps)`
- `write_marker(marker, lsl_timestamp)`
- `close()`
- `path`
- `sample_counts`
- `is_closed`

This is acceptable for the current MVP because the package is small and the
capture ordering is clear: write XDF first, then write DB rows.

## Current Modality Configuration

XDF stream definitions currently live in `capture/xdf/constants.py`.

The important maps are:

- `STREAM_IDS`
- `BIOSIGNAL_STREAM_IDS`
- `CHANNEL_COUNTS`
- `SAMPLE_RATES`

This means a modality is not defined in one complete object. Instead, each
piece of modality identity is distributed across several maps. That is fine for
the current five streams, but it becomes easier to make a mistake when adding a
new modality.

Example risk: a future modality could be added to `STREAM_IDS` but missed in
`CHANNEL_COUNTS` or `SAMPLE_RATES`. The failure would probably appear later at
runtime when metadata is built or samples are encoded.

## Known Risk

`write_samples()` and `write_marker()` currently catch `OSError`, log the
failure, and return without raising to the caller.

That behavior keeps capture running, but it weakens the core durability
contract. If XDF writes fail mid-session, the DB path may continue, but XDF is
no longer complete enough to serve as reconciliation ground truth.

This is already tracked in `docs/phase-2-reviews/db-health.md`:

- `bugs.md MED-09`
- Rollup #7, "XDF write-failure visibility"

Do not create a duplicate DB-health issue for this. The future fix should
probably escalate repeated or any mid-session XDF write failure to the watchdog
or operator, because XDF is the source of truth for recovery.

## Future Refactor Direction

Do not introduce a generic persistence manager yet. That would be a larger
architecture change than this package needs right now.

The first useful future refactor is to make `constants.py` more rigid by
defining one canonical XDF stream spec per modality.

Possible shape:

```python
@dataclass(frozen=True)
class XDFStreamSpec:
    name: str
    stream_id: int
    channel_count: int
    sample_rate: float
    sample_format: str
    stream_type: str
    is_biosignal: bool
```

Then define one registry:

```python
XDF_STREAM_SPECS = {
    "EEG": XDFStreamSpec(...),
    "HRV": XDFStreamSpec(...),
    "EDA": XDFStreamSpec(...),
    "Respiration": XDFStreamSpec(...),
    "ECHO": XDFStreamSpec(...),
}
```

During a gradual migration, the old maps can be derived from this registry:

```python
STREAM_IDS = {name: spec.stream_id for name, spec in XDF_STREAM_SPECS.items()}
BIOSIGNAL_STREAM_IDS = {
    name: spec.stream_id
    for name, spec in XDF_STREAM_SPECS.items()
    if spec.is_biosignal
}
CHANNEL_COUNTS = {
    name: spec.channel_count
    for name, spec in XDF_STREAM_SPECS.items()
}
SAMPLE_RATES = {
    name: spec.sample_rate
    for name, spec in XDF_STREAM_SPECS.items()
}
```

That keeps the external API stable while making modality registration harder to
partially update.

## Adding a New Modality Checklist

When adding a new stream, check the whole capture path, not just XDF:

- Add a stable XDF stream ID.
- Define channel count.
- Define nominal sample rate through `config/settings.py` when runtime
  configurable.
- Decide whether the stream is biosignal float data or marker/string data.
- Update XDF stream-header metadata.
- Update XDF payload encoding if the sample shape differs from existing
  biosignal chunks.
- Add the DB migration and write path for raw records.
- Add or update the forwarder stream thread config.
- Confirm session-close reconciliation can count and backfill the modality.
- Confirm downstream batch or ARC code either consumes or intentionally ignores
  the modality.

For the current codebase, the safest time to refactor `constants.py` into a
single stream-spec registry is when the next modality is added. Before then, the
current maps are simple enough to leave alone.
