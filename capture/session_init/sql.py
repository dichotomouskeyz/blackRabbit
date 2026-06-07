"""SQL statements for session initialization."""

SESSION_INSERT = """
    INSERT INTO sessions (
        id, site_id, sponsor_id, participant_id,
        capture_mode, compound, compound_dose, compound_dose_unit,
        protocol_arm, room_id,
        status, started_at
    ) VALUES (
        %(id)s, %(site_id)s, %(sponsor_id)s, %(participant_id)s,
        %(capture_mode)s, %(compound)s, %(compound_dose)s, %(compound_dose_unit)s,
        %(protocol_arm)s, %(room_id)s,
        'initializing', NOW()
    )
"""

SESSION_ACTIVATE = "UPDATE sessions SET status = 'active' WHERE id = %s"

_METADATA_INSERT = """
    INSERT INTO session_signal_metadata (
        session_id, site_id, sponsor_id, participant_id, device_id,
        device_type,
        modality,
        power_line_frequency, sample_rate_hz, software_filters,
        eeg_reference, sampling_frequency, eeg_channel_count, eeg_channel_names,
        cap_manufacturer, cap_manufacturer_model_name,
        eeg_electrode_type, eeg_skin_prep,
        hrv_signal_source, beat_detection_algorithm, beat_detection_version,
        electrode_placement, electrode_type, skin_prep,
        eda_signal_source, eda_range_min_us, eda_range_max_us,
        respiration_source, is_derived, respiration_unit
    ) VALUES (
        %(session_id)s, %(site_id)s, %(sponsor_id)s, %(participant_id)s, %(device_id)s,
        %(device_type)s,
        %(modality)s,
        %(power_line_frequency)s, %(sample_rate_hz)s, %(software_filters)s,
        %(eeg_reference)s, %(sampling_frequency)s, %(eeg_channel_count)s, %(eeg_channel_names)s,
        %(cap_manufacturer)s, %(cap_manufacturer_model_name)s,
        %(eeg_electrode_type)s, %(eeg_skin_prep)s,
        %(hrv_signal_source)s, %(beat_detection_algorithm)s, %(beat_detection_version)s,
        %(electrode_placement)s, %(electrode_type)s, %(skin_prep)s,
        %(eda_signal_source)s, %(eda_range_min_us)s, %(eda_range_max_us)s,
        %(respiration_source)s, %(is_derived)s, %(respiration_unit)s
    )
"""

_SCHEMA_VERSION_INSERT = """
    INSERT INTO schema_version_log (
        session_id, site_id, sponsor_id,
        alembic_version, app_version, python_version,
        postgres_version, timescaledb_version, pgvector_version,
        mne_version, neurokit2_version, pylsl_version
    ) VALUES (
        %(session_id)s, %(site_id)s, %(sponsor_id)s,
        %(alembic_version)s, %(app_version)s, %(python_version)s,
        %(postgres_version)s, %(timescaledb_version)s, %(pgvector_version)s,
        %(mne_version)s, %(neurokit2_version)s, %(pylsl_version)s
    )
"""
