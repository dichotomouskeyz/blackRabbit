"""BrainFlow implementation of the acquisition-only adapter contract."""

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams
from brainflow.exit_codes import BrainFlowError, BrainFlowExitCodes

from capture.hardware.configuration import BridgeConfig, DeviceBinding
from capture.hardware.errors import HardwareError, ValidationError
from capture.hardware.profiles import DeviceProfile


@dataclass(frozen=True)
class BoardBatch:
    preset: int
    data: np.ndarray


class Adapter(Protocol):
    def prepare(self) -> None: ...
    def start(self) -> None: ...
    def read(self) -> list[BoardBatch]: ...
    def stop(self) -> None: ...
    def release(self) -> None: ...


def board_layout(board_id: int, preset: int) -> dict[str, Any]:
    try:
        if board_id < -1:
            raise ValueError("Unsupported virtual board")
        BoardIds(board_id)
        return BoardShim.get_board_descr(board_id, preset)
    except (BrainFlowError, ValueError) as exc:
        raise ValidationError(
            "Board/preset is unavailable in the installed BrainFlow version"
        ) from exc


def validate_profile_layout(profile: DeviceProfile) -> dict[int, dict]:
    layouts = {}
    for preset in profile.presets:
        layout = board_layout(profile.board_id, preset.preset)
        if layout["sampling_rate"] != preset.sampling_rate:
            raise ValidationError("Profile rate disagrees with BrainFlow model metadata")
        reserved = {layout["timestamp_channel"], layout.get("package_num_channel", -1)}
        for signal in preset.signals:
            if any(r >= layout["num_rows"] or r in reserved for r in signal.rows):
                raise ValidationError("Signal maps outside the layout or onto a reserved row")
        layouts[preset.preset] = layout
    return layouts


def validate_config(config: BridgeConfig) -> dict:
    """Validate model metadata without creating or preparing a BoardShim."""
    devices = []
    for binding in config.bindings:
        validate_profile_layout(binding.profile)
        devices.append(
            {
                "source_id": binding.source_id,
                "profile_id": binding.profile.id,
                "profile_version": binding.profile.version,
                "profile_hash": binding.profile.content_hash,
                "source_kind": "simulated" if binding.profile.board_id == -1 else "hardware",
                "connection_verified": False,
            }
        )
    return {"schema_version": 1, "valid": True, "devices": devices}


def inspect_board(board_id: int) -> dict:
    """A draft with explicit gaps; descriptor alternatives are not assignments."""
    board_layout(board_id, 0)
    presets = []
    for preset in sorted(BoardShim.get_board_presets(board_id)):
        layout = board_layout(board_id, int(preset))
        alternatives = {k: v for k, v in layout.items() if k.endswith("_channels")}
        by_row: dict[int, list[str]] = {}
        for name, rows in alternatives.items():
            for row in rows:
                by_row.setdefault(row, []).append(name)
        presets.append(
            {
                "preset": int(preset),
                "model_metadata": layout,
                "signal_alternatives": alternatives,
                "ambiguous_rows": {str(k): v for k, v in by_row.items() if len(v) > 1},
            }
        )
    return {
        "schema_version": 1,
        "status": "draft",
        "board_id": board_id,
        "presets": presets,
        "connection_verified": False,
        "unresolved": [
            "signal assignments and physical wiring",
            "source/output units",
            "timestamp origin",
            "connection parameters",
            "physical test evidence",
        ],
    }


class BrainFlowAdapter:
    def __init__(self, binding: DeviceBinding, buffer_seconds: float) -> None:
        self.binding = binding
        self.layouts = validate_profile_layout(binding.profile)
        self.capacity = max(
            2, int(np.ceil(max(p.sampling_rate for p in binding.profile.presets) * buffer_seconds))
        )
        params = BrainFlowInputParams()
        params.timeout = 10
        if binding.profile.board_id == -1:
            # BrainFlow keys native sessions by board ID and complete input parameters.
            params.other_info = f"blackrabbit:{binding.source_id}"
        for key, value in binding.parameters:
            setattr(params, key, value)
        self.board = BoardShim(binding.profile.board_id, params)
        self._start_attempted = False

    def prepare(self) -> None:
        # Native INFO logs include connection parameters. Use our structured lifecycle logs.
        BoardShim.disable_board_logger()
        self.board.prepare_session()

    def start(self) -> None:
        self._start_attempted = True
        self.board.start_stream(self.capacity)

    def read(self) -> list[BoardBatch]:
        batches = []
        for preset in self.binding.profile.presets:
            count = self.board.get_board_data_count(preset.preset)
            if count >= self.capacity:
                raise HardwareError("buffer_capacity_reached", "Native buffer reached capacity")
            if not count:
                continue
            data = self.board.get_board_data(self.capacity, preset.preset)
            if data.shape[1] >= self.capacity:
                raise HardwareError("buffer_capacity_reached", "Native buffer reached capacity")
            batches.append(BoardBatch(preset.preset, data))
        return batches

    def stop(self) -> None:
        if self._start_attempted:
            self._start_attempted = False
            try:
                self.board.stop_stream()
            except BrainFlowError as exc:
                # A failed start has no running thread to stop; still release the session.
                if exc.exit_code != BrainFlowExitCodes.STREAM_THREAD_IS_NOT_RUNNING.value:
                    raise

    def release(self) -> None:
        if self.board.is_prepared():
            self.board.release_session()
