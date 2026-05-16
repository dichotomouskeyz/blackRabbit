from config import settings

_XDF_MAGIC = b"XDF:"

_TAG_FILE_HEADER = 1
_TAG_STREAM_HEADER = 2
_TAG_SAMPLES = 3
_TAG_STREAM_FOOTER = 6

_STREAM_IDS: dict[str, int] = {
    "EEG": 1,
    "HRV": 2,
    "EDA": 3,
    "Respiration": 4,
    "ECHO": 5,
}

# Biosignal streams only — ECHO uses a separate string encoding path
_BIOSIGNAL_STREAM_IDS: dict[str, int] = {k: v for k, v in _STREAM_IDS.items() if k != "ECHO"}

_CHANNEL_COUNTS: dict[str, int] = {
    "EEG": settings.EEG_CHANNEL_COUNT,
    "HRV": 1,
    "EDA": 1,
    "Respiration": 1,
    "ECHO": 1,
}

_SAMPLE_RATES: dict[str, float] = {
    "EEG": float(settings.SAMPLE_RATE_EEG),
    "HRV": float(settings.SAMPLE_RATE_HRV),
    "EDA": float(settings.SAMPLE_RATE_EDA),
    "Respiration": float(settings.SAMPLE_RATE_RESPIRATION),
    "ECHO": 0.0,  # irregular — event-driven
}
