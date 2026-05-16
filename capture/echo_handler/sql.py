"""SQL statements for ECHO writes."""

ECHO_INSERT = """
    INSERT INTO echo_events (
        session_id, participant_id, site_id, sponsor_id,
        event_type, source, actor_id, actor_role,
        zone_label, lsl_timestamp
    ) VALUES (
        %(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s,
        %(event_type)s, 'manual_logging', %(actor_id)s, %(actor_role)s,
        %(zone_label)s, %(lsl_timestamp)s
    )
"""
