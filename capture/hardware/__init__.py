"""Headless source acquisition. Importing this package starts no devices."""

from capture.hardware.adapter import Adapter, inspect_board, validate_config
from capture.hardware.configuration import BridgeConfig, DeviceBinding, load_config
from capture.hardware.discovery import discover
from capture.hardware.profiles import DeviceProfile, load_profile, synthetic_profile
from capture.hardware.runtime import run_bridge

__all__ = [
    "Adapter",
    "BridgeConfig",
    "DeviceBinding",
    "DeviceProfile",
    "discover",
    "inspect_board",
    "load_config",
    "load_profile",
    "run_bridge",
    "synthetic_profile",
    "validate_config",
]
