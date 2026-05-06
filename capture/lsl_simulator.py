"""Synthetic LSL stream simulator for development and testing.

Outputs four biosignal streams that match exactly what lsl_forwarder.py
expects from real hardware. Run this in one terminal, then lsl_forwarder.py
in another when no physical devices are connected.

Streams published:
  EEG          8 channels, 256 Hz — alpha/beta/theta/delta/gamma mix + noise
  HRV          1 channel  (RR interval ms), ~1 Hz — RSA + Mayer wave modulation
  EDA          1 channel  (µS), 4 Hz — tonic baseline + phasic SCR events
  Respiration  1 channel  (normalized -1..1), 4 Hz — 0.25 Hz respiratory cycle

Usage:
    python -m capture.lsl_simulator
    python capture/lsl_simulator.py
"""

import math
import random
import threading
import time

import pylsl

from capture.logger import get_logger, set_session_id
from config import settings

settings.validate()

log = get_logger("lsl_simulator")
set_session_id(None)  # no session during simulation

_stop = threading.Event()

# Simulator hardware rates — these represent the device, not the app config.
# EEG uses 256 Hz (2^8) matching common research headsets (OpenBCI, Enobio).
_EEG_RATE = 256
_HRV_RATE = 1  # samples/sec; interval varies to simulate RR jitter
_EDA_RATE = 4  # Hz — clinical floor; device can push up to 32 Hz
_RESP_RATE = 4  # Hz sample rate; waveform oscillates at ~0.25 Hz


# ---------------------------------------------------------------------------
# EEG — 8 channels, 256 Hz
# Each channel is a superposition of all five canonical EEG bands with a
# unique phase offset so adjacent channels are not perfectly correlated.
# Amplitudes are in µV, consistent with scalp EEG from gel electrodes.
# ---------------------------------------------------------------------------
def _run_eeg() -> None:
    info = pylsl.StreamInfo(
        name=settings.LSL_STREAM_EEG,
        type="EEG",
        channel_count=settings.EEG_CHANNEL_COUNT,
        nominal_srate=_EEG_RATE,
        channel_format=pylsl.cf_float32,
        source_id="consensai_sim_eeg",
    )
    outlet = pylsl.StreamOutlet(info)
    log.info(
        "EEG stream open",
        extra={"rate_hz": _EEG_RATE, "channels": settings.EEG_CHANNEL_COUNT},
    )

    phases = [random.uniform(0, 2 * math.pi) for _ in range(settings.EEG_CHANNEL_COUNT)]
    interval = 1.0 / _EEG_RATE
    t = 0.0
    next_tick = time.monotonic()

    while not _stop.is_set():
        sample = []
        for ch in range(settings.EEG_CHANNEL_COUNT):
            ph = phases[ch]
            val = (
                50.0 * math.sin(2 * math.pi * 1.5 * t + ph)  # delta  1.5 Hz
                + 30.0 * math.sin(2 * math.pi * 6.0 * t + ph)  # theta  6 Hz
                + 40.0 * math.sin(2 * math.pi * 10.0 * t + ph)  # alpha  10 Hz
                + 20.0 * math.sin(2 * math.pi * 20.0 * t + ph)  # beta   20 Hz
                + 10.0 * math.sin(2 * math.pi * 40.0 * t + ph)  # gamma  40 Hz
                + random.gauss(0, 5.0)  # noise
            )
            sample.append(val)

        outlet.push_sample(sample)
        t += interval

        next_tick += interval
        wait = next_tick - time.monotonic()
        if wait > 0:
            time.sleep(wait)


# ---------------------------------------------------------------------------
# HRV — 1 channel (RR interval in ms), ~1 Hz
# Simulates heart rate variability with two physiological components:
#   RSA  (respiratory sinus arrhythmia) — HF band, ~0.25 Hz, ±30 ms
#   Mayer waves                         — LF band, ~0.10 Hz, ±20 ms
# Base HR: 70 bpm → 857 ms mean RR interval
# ---------------------------------------------------------------------------
def _run_hrv() -> None:
    info = pylsl.StreamInfo(
        name=settings.LSL_STREAM_HRV,
        type="HRV",
        channel_count=1,
        nominal_srate=_HRV_RATE,
        channel_format=pylsl.cf_float32,
        source_id="consensai_sim_hrv",
    )
    outlet = pylsl.StreamOutlet(info)
    log.info("HRV stream open", extra={"rate_hz": _HRV_RATE})

    t = 0.0

    while not _stop.is_set():
        rsa = 30.0 * math.sin(2 * math.pi * 0.25 * t)  # RSA
        mayer = 20.0 * math.sin(2 * math.pi * 0.10 * t)  # Mayer waves
        noise = random.gauss(0, 8.0)
        rr_ms = 857.0 + rsa + mayer + noise  # ~70 bpm base
        rr_ms = max(400.0, min(1400.0, rr_ms))  # physiological clamp

        outlet.push_sample([rr_ms])
        t += 1.0 / _HRV_RATE

        # Sleep the actual RR interval so push rate matches simulated heart rate
        time.sleep(rr_ms / 1000.0)


# ---------------------------------------------------------------------------
# EDA — 1 channel (skin conductance, µS), 4 Hz
# Tonic baseline drifts slowly between 2–10 µS.
# Phasic SCRs (skin conductance responses) fire at ~0.05 Hz: rapid rise
# over ~0.5 s, exponential decay with a 3 s time constant.
# ---------------------------------------------------------------------------
def _run_eda() -> None:
    info = pylsl.StreamInfo(
        name=settings.LSL_STREAM_EDA,
        type="EDA",
        channel_count=1,
        nominal_srate=_EDA_RATE,
        channel_format=pylsl.cf_float32,
        source_id="consensai_sim_eda",
    )
    outlet = pylsl.StreamOutlet(info)
    log.info("EDA stream open", extra={"rate_hz": _EDA_RATE})

    interval = 1.0 / _EDA_RATE
    t = 0.0
    next_tick = time.monotonic()

    tonic = 5.0  # µS baseline
    scr_amplitude = 0.0  # current phasic response amplitude
    scr_decay = 3.0  # time constant (seconds)
    scr_rate = 0.05  # events per second (~1 per 20 s)

    while not _stop.is_set():
        # Tonic drift — slow sine + small noise
        tonic = 5.0 + 3.0 * math.sin(2 * math.pi * 0.01 * t)

        # Probabilistic SCR onset
        if random.random() < scr_rate * interval:
            scr_amplitude += random.uniform(0.5, 2.0)
            log.info("SCR fired", extra={"amplitude_us": round(scr_amplitude, 3)})

        # Phasic decay
        scr_amplitude *= math.exp(-interval / scr_decay)

        val = tonic + scr_amplitude + random.gauss(0, 0.05)
        val = max(0.0, val)
        outlet.push_sample([val])
        t += interval

        next_tick += interval
        wait = next_tick - time.monotonic()
        if wait > 0:
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Respiration — 1 channel (normalized -1..1), 4 Hz sample rate
# Waveform oscillates at 0.25 Hz (15 breaths/min, normal resting rate).
# Slight asymmetry: inhale is faster than exhale (ratio 2:3).
# ---------------------------------------------------------------------------
def _run_respiration() -> None:
    info = pylsl.StreamInfo(
        name=settings.LSL_STREAM_RESPIRATION,
        type="Respiration",
        channel_count=1,
        nominal_srate=_RESP_RATE,
        channel_format=pylsl.cf_float32,
        source_id="consensai_sim_respiration",
    )
    outlet = pylsl.StreamOutlet(info)
    log.info(
        "Respiration stream open", extra={"rate_hz": _RESP_RATE, "breath_hz": 0.25}
    )

    interval = 1.0 / _RESP_RATE
    t = 0.0
    next_tick = time.monotonic()
    breath_freq = 0.25  # Hz — 15 breaths/min

    while not _stop.is_set():
        # Asymmetric waveform: skewed sine approximates inhale/exhale ratio
        phase = (t * breath_freq % 1.0) * 2 * math.pi
        val = math.sin(phase) - 0.2 * math.sin(2 * phase)
        val += random.gauss(0, 0.02)
        outlet.push_sample([val])
        t += interval

        next_tick += interval
        wait = next_tick - time.monotonic()
        if wait > 0:
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    log.info(
        "simulator starting",
        extra={
            "streams": ["EEG", "HRV", "EDA", "Respiration"],
            "eeg_hz": _EEG_RATE,
            "hrv_hz": _HRV_RATE,
            "eda_hz": _EDA_RATE,
            "resp_hz": _RESP_RATE,
        },
    )

    threads = [
        threading.Thread(target=_run_eeg, name="sim_eeg", daemon=True),
        threading.Thread(target=_run_hrv, name="sim_hrv", daemon=True),
        threading.Thread(target=_run_eda, name="sim_eda", daemon=True),
        threading.Thread(target=_run_respiration, name="sim_resp", daemon=True),
    ]

    for t in threads:
        t.start()

    log.info("all streams live — press Ctrl+C to stop")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("shutdown requested")
        _stop.set()
        for t in threads:
            t.join(timeout=3.0)
        log.info("simulator stopped")


if __name__ == "__main__":
    main()
