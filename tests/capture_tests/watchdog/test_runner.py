"""Unit tests for watchdog runner entry-point behavior."""

import importlib
from unittest.mock import patch

import pytest


def test_runner_import_does_not_validate_settings():
    import capture.watchdog.runner as runner

    with patch.object(runner.settings, "validate") as validate:
        importlib.reload(runner)

    validate.assert_not_called()


def test_main_validates_settings_before_parsing_args():
    import capture.watchdog.runner as runner

    with (
        patch.object(runner.settings, "validate") as validate,
        patch.object(runner, "parse_args", side_effect=RuntimeError("stop after validate")),
    ):
        with pytest.raises(RuntimeError, match="stop after validate"):
            runner.main()

    validate.assert_called_once()
