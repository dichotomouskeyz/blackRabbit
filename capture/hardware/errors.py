"""Stable error codes for CLI and local callers."""


class HardwareError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ValidationError(HardwareError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_configuration", message)
