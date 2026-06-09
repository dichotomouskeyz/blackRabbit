# Forwarder Refactor Suggestions

## capture/forwarder/runtime.py
### Current State
The `run_forwarder` function is implemented as a procedural script. It handles session validation, configuration loading, thread management, and teardown in a single linear block. This creates tight coupling and makes the system fragile; changing one part of the startup sequence risks breaking the entire pipeline.

### Proposed Refactor: `ForwarderEngine` (OOP Approach)
Transition from a procedural function to a state-managed class. This decouples the "Validation" phase from the "Execution" phase.

#### Architecture
- **`__init__(cfg)`**: Initializes state (threads, stop events, XDF writer).
- **`prepare()`**: Handles `verify_session_ready` and `load_session_config`. Allows for validation without starting streams.
- **`start()`**: Manages the ignition sequence (XDF initialization, thread spawning, OS signal registration).
- **`run_until_stopped()`**: Replaces `_wait_for_stop`. The monitoring loop for stop requests and heartbeat.
- **`stop()`**: Replaces `_join_threads` logic. Ensures a guaranteed clean shutdown (joining threads, closing files).

#### Benefits
- **Isolation**: Changes to teardown logic won't affect preflight checks.
- **Testability**: Enables unit testing the `prepare()` phase without needing active LSL streams.
- **Flexibility**: Allows the system to be controlled by an external manager (e.g., a GUI or a supervisor process) via method calls rather than a single function execution.
- **State Management**: The engine "owns" its lifecycle state, reducing the need for global flags or complex argument passing.

#### Implementation Strategy
Retain the `run_forwarder` function as a thin wrapper to maintain backward compatibility with the CLI:
```python
def run_forwarder(cfg: SessionConfig) -> None:
    engine = ForwarderEngine(cfg)
    engine.prepare()
    engine.start()
    engine.run_until_stopped()
    engine.stop()
```

### Logging Gap: Simulation vs Hardware
Currently, simulation mode is primarily noted at startup. To improve observability, the system should use the `CAPTURE_SOURCE` setting as the source of truth for all runtime logs.

- **The Fix**: Implement a logging context or helper that automatically attaches the `CAPTURE_SOURCE` (e.g., `"simulated"` or `"hardware"`) to every log entry.
- **Benefit**: Allows for instant filtering of logs during analysis to distinguish between real patient data and simulation tests.

## capture/forwarder/preflight.py
1. **The "Double-Dip" Connection (Performance)**
   Right now, `_verify_session_ready` opens and closes a connection, and then `_load_session_config` opens and closes another one.
   - **The Fix**: Instead of the functions managing their own connections, they should accept a connection object as an argument.
   - **Why**: Opening a TCP connection to a database is "expensive" (slow). Doing it twice in a row is wasteful.

2. **Hardcoded Requirements (Flexibility)**
   `_REQUIRED_MODALITIES` is hardcoded inside the file.
   - **The Fix**: Move that list into `config/settings.py`.
   - **Why**: If you add a new sensor (like Eye Tracking) next month, you shouldn't have to dig into the logic files to change a list; you should just change a config setting.

3. **Generic Errors (Granularity)**
   You use `RuntimeError` for every single failure.
   - **The Fix**: Create custom exception classes:
     - `SessionNotFoundError`
     - `SessionNotActiveError`
     - `MissingModalityError`
   - **Why**: Right now, `runtime.py` just knows "something went wrong." If you have specific errors, `runtime.py` could potentially try to fix the problem (e.g., "The session is inactive... let me try to activate it for you") instead of just crashing.
