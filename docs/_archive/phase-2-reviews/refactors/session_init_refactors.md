# Session Init Refactor Suggestions

## Overview
The `capture/session_init` package currently operates as a "Data Pipeline of Strings," where session configuration is passed as a long list of individual arguments through multiple layers of functions. This creates high coupling and significant fragility when extending the database schema.

---

## 1. The Propagating Parameter Problem
### Current State
`cli.py` $ightarrow$ `workflow.py` (`create_session`) $ightarrow$ `metadata.py` (`_build_metadata_rows`) $ightarrow$ modality helpers.
The system passes ~17 individual arguments (site\_id, sponsor\_id, electrode\_type, etc.) through every single function call in the chain.

### Proposed Refactor: `SessionRequest` Dataclass
Introduce a typed dataclass to encapsulate all initialization data.

- **The Change**: Replace the long list of arguments in `create_session` and `_build_metadata_rows` with a single `request: SessionRequest` object.
- **Benefit**: Adding a new field to the session initialization now only requires updating the dataclass and the final SQL insert, rather than updating every function signature in the call stack.

---

## 2. The Implicit Schema Problem
### Current State
`metadata.py` uses a `_null_metadata_fields()` dictionary to provide a template of `None` values for SQL inserts. This effectively creates a "shadow schema" in Python code.

### Proposed Refactor: Inherited Metadata Models
Replace the "null dictionary" approach with a class-based hierarchy.

- **The Change**:
    - Create a `BaseMetadata` class for universal fields (session\_id, participant\_id, etc.).
    - Create modality-specific subclasses (e.g., `EEGMetadata`, `HRVMetadata`) that add their own specific fields.
- **Benefit**: Strong typing and clear visibility into what data is required for each modality, removing the reliance on a "magic" dictionary of nulls.

---

## 3. The Manual Transaction Problem
### Current State
`workflow.py` manually manages the database lifecycle using `conn.commit()` and `conn.rollback()` inside a large `try...except` block.

### Proposed Refactor: Repository Pattern
Move database interaction logic out of the workflow and into a dedicated repository.

- **The Change**: Create a `SessionRepository` class. The workflow should call high-level methods like `repo.create_session_anchor()` and `repo.save_signal_metadata()`.
- **Benefit**: Separates "Business Logic" (the steps to init a session) from "Persistence Logic" (how the data is written to Postgres).

---

## 4. The CLI-to-Logic Leak
### Current State
Input validation (UUID checks, choice lists) is trapped inside `argparse` in `cli.py`.

### Proposed Refactor: Dedicated Validation Layer
Move validation logic out of the CLI and into the `SessionRequest` object or a standalone validator.

- **The Change**: Use `__post_init__` in the `SessionRequest` dataclass or a separate `validate_request()` function to check UUIDs and valid choices.
- **Benefit**: Allows the system to initialize sessions via other interfaces (API, GUI, or scripts) without duplicating the validation logic.

---

## Summary of Architectural Shift

**Current Flow (Procedural):**
`CLI Args` $ightarrow$ `create_session(17 args)` $ightarrow$ `_build_metadata(17 args)` $ightarrow$ `SQL Insert`

**Proposed Flow (Object-Oriented):**
`CLI Args` $ightarrow$ `SessionRequest Object` $ightarrow$ `SessionRepository.init_session(request)` $ightarrow$ `MetadataModels` $ightarrow$ `SQL Insert`
