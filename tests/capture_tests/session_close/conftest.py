"""Guard the session_close import-time `settings.validate()` (session-close.md Risk).

Importing `capture.session_close.workflow` calls `settings.validate()` at module
level, which raises without a fully valid environment. We neutralise `validate`
only for the duration of that one import, then restore it, so no other test's
view of `settings.validate` is affected (the module is cached after first import).
"""

import config.settings as settings

_orig_validate = settings.validate
settings.validate = lambda: None
try:  # noqa: SIM105 - explicit for clarity
    import capture.session_close.workflow  # noqa: F401
finally:
    settings.validate = _orig_validate
