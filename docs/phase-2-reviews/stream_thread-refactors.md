# Stream Thread Refactor Suggestions

## capture/forwarder/stream_thread/streams.py

### Current State
The `build_stream_threads` function is currently implemented as a procedural list of manual instantiations. For every modality (EEG, HRV, EDA, Respiration), a `StreamThread` object is created with a long list of repetitive arguments (e.g., `cfg`, `stop_event`, `xdf_writer`).

This approach is:
- **Repetitive**: The same context objects are passed to every thread.
- **Fragile**: Adding a new modality requires duplicating a large block of code.
- **Hard to Maintain**: Changes to the `StreamThread` constructor require updates in four different locations.

### Proposed Refactor: `StreamFactory` (Factory Pattern)
Transition from a manual list to a data-driven Factory class. This decouples the "What to build" (configuration) from the "How to build" (instantiation).

#### Architecture
- **`StreamFactory` Class**:
    - **`__init__(cfg, stop, xdf)`**: Stores the shared context used by all threads.
    - **`create_threads()`**: Loops through a modality configuration map to instantiate threads.
- **Modality Configuration Map**:
    - A dictionary mapping modality names (e.g., `"EEG"`, `"HRV"`) to their specific settings (SQL, table name, row builder, chunk size).

#### Benefits
- **DRY (Don't Repeat Yourself)**: Context objects (`cfg`, `stop`, `xdf`) are passed once to the factory, not repeated for every thread.
- **Scalability**: Adding a new modality (e.g., Eye Tracking) only requires adding a single entry to the configuration map.
- **Consistency**: Ensures that all `StreamThread` instances are created using the same logic and patterns.

#### Implementation Strategy
1. Define a `MODALITY_CONFIGS` dictionary containing the unique parameters for each signal type.
2. Implement the `StreamFactory` class to handle the loop.
3. Update `capture/forwarder/runtime.py` to use the factory instead of the standalone function.

**Example Pseudo-code:**
```python
class StreamFactory:
    def __init__(self, cfg, stop, xdf):
        self.cfg = cfg
        self.stop = stop
        self.xdf = xdf

    def create_threads(self) -> list[threading.Thread]:
        threads = []
        for modality, params in MODALITY_CONFIGS.items():
            threads.append(StreamThread(
                stream_name=params["stream_name"],
                stream_type=modality,
                chunk_size=params["chunk_size"],
                row_builder=params["builder"],
                insert_sql=params["sql"],
                cfg=self.cfg,
                stop_event=self.stop,
                xdf_writer=self.xdf,
                table_name=params["table"],
                hash_fields=params["hash_fields"],
                hash_sort_keys=params["hash_keys"],
            ))
        threads.append(self._build_echo_thread())
        return threads
```

## The "Pass-the-Object" Pattern
### Current State
The `StreamThread` class acts as a "data bag," where the thread object is passed as the first argument to nearly every helper function in the package (e.g., `process_chunk(thread, ...)`, `write_rows(thread, ...)`).

This creates a fragile dependency: if a property name changes within `StreamThread`, the system will not fail at startup, but will instead crash at runtime when a helper function attempts to access the missing property.

### Proposed Refactor: True Method Encapsulation
Move the logic from the helper files (`stream_db.py`, `stream_chunks.py`, `stream_drift.py`, `stream_integrity.py`) directly into the `StreamThread` class as methods.

- **The Change**: Transition from `helper_func(thread, ...)` to `thread.helper_method(...)`.
- **Benefit**:
    - **Encapsulation**: Logic lives where the data lives.
    - **Type Safety**: The IDE and linter can validate method calls at development time.
    - **Readability**: Reduces the need to jump between 5+ files to understand the lifecycle of a single thread.
