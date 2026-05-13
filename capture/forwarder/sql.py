"""Forwarder INSERT statements."""

_EEG_INSERT = """
    INSERT INTO eeg_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         channel_id, voltage, lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(channel_id)s, %(voltage)s, %(lsl_timestamp)s, %(sample_index)s)
"""

_HRV_INSERT = """
    INSERT INTO hrv_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         rr_interval_ms, heart_rate_bpm, beat_quality, lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(rr_interval_ms)s, %(heart_rate_bpm)s, %(beat_quality)s,
         %(lsl_timestamp)s, %(sample_index)s)
"""

_EDA_INSERT = """
    INSERT INTO eda_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         raw_conductance_us, conductance_us, signal_quality, lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(raw_conductance_us)s, %(conductance_us)s, %(signal_quality)s,
         %(lsl_timestamp)s, %(sample_index)s)
"""

_RESPIRATION_INSERT = """
    INSERT INTO respiration_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         raw_amplitude, processed_amplitude, breath_phase, breaths_per_min,
         lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(raw_amplitude)s, %(processed_amplitude)s, %(breath_phase)s, %(breaths_per_min)s,
         %(lsl_timestamp)s, %(sample_index)s)
"""

_CLOCK_DRIFT_INSERT = """
    INSERT INTO clock_drift_log (
        session_id, participant_id, site_id, sponsor_id, device_id,
        stream_type, remote_clock_offset_s, exceeds_threshold, threshold_s,
        lsl_timestamp
    ) VALUES (
        %(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
        %(stream_type)s, %(remote_clock_offset_s)s, %(exceeds_threshold)s, %(threshold_s)s,
        %(lsl_timestamp)s
    )
"""
