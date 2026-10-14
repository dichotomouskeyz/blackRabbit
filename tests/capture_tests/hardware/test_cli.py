"""HW-011: stable machine-readable local interface."""

import json
from pathlib import Path

from capture.hardware.cli import main


def test_cli_inspection_and_validation_return_json(capsys):
    assert main(["inspect", "--board-id", "-1"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "draft"
    example = Path(__file__).parents[3] / "capture/hardware/examples/synthetic.json"
    assert main(["validate", "--config", str(example)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_cli_invalid_config_has_error_code(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version": 99, "bindings": []}')
    assert main(["validate", "--config", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "invalid_configuration"
