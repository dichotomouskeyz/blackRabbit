"""Tests for audit triggers firing on INSERT into key tables."""

from uuid import uuid4


class TestAuditTriggers:
    def test_biosignal_tables_do_not_have_row_audit_triggers(self, cursor):
        cursor.execute("""
            SELECT tgrelid::regclass::text
            FROM pg_trigger
            WHERE NOT tgisinternal
              AND tgname IN (
                  'eeg_samples_audit_trigger',
                  'hrv_samples_audit_trigger',
                  'eda_samples_audit_trigger',
                  'respiration_samples_audit_trigger'
              )
            ORDER BY 1;
        """)
        assert cursor.fetchall() == []

    def test_session_update_triggers_status_transition_audit(self, cursor):
        sid = str(uuid4())
        cursor.execute(
            """
            INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
            VALUES (
                %s,
                'a0eebc99-0000-0000-0000-000000000001',
                'a0eebc99-0000-0000-0000-000000000002',
                'a0eebc99-0000-0000-0000-000000000003',
                'psilocybin', 'initializing'
            );
            """,
            (sid,),
        )
        cursor.execute("UPDATE sessions SET status = 'active' WHERE id = %s", (sid,))

        cursor.execute(
            """
            SELECT payload->>'old_status', payload->>'new_status'
            FROM audit_events
            WHERE session_id = %s AND event_type = 'session_status_transition'
            """,
            (sid,),
        )
        assert cursor.fetchall() == [("initializing", "active")]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM audit_events
            WHERE session_id = %s
              AND event_type IN ('watermark_verified', 'watermark_failed')
            """,
            (sid,),
        )
        assert cursor.fetchone()[0] == 0

    def test_session_update_triggers_transition_and_verified_watermark(self, cursor):
        sid = str(uuid4())
        cursor.execute(
            """
            INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
            VALUES (
                %s,
                'a0eebc99-0000-0000-0000-000000000001',
                'a0eebc99-0000-0000-0000-000000000002',
                'a0eebc99-0000-0000-0000-000000000003',
                'psilocybin', 'closing'
            );
            """,
            (sid,),
        )
        cursor.execute(
            "UPDATE sessions SET status = 'closed', closed_at = NOW() WHERE id = %s",
            (sid,),
        )

        cursor.execute(
            """
            SELECT event_type
            FROM audit_events
            WHERE session_id = %s
              AND event_type IN ('session_status_transition', 'watermark_verified')
            ORDER BY id
            """,
            (sid,),
        )
        assert [row[0] for row in cursor.fetchall()] == [
            "session_status_transition",
            "watermark_verified",
        ]

    def test_session_update_triggers_transition_and_failed_watermark(self, cursor):
        sid = str(uuid4())
        cursor.execute(
            """
            INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
            VALUES (
                %s,
                'a0eebc99-0000-0000-0000-000000000001',
                'a0eebc99-0000-0000-0000-000000000002',
                'a0eebc99-0000-0000-0000-000000000003',
                'psilocybin', 'active'
            );
            """,
            (sid,),
        )
        cursor.execute(
            "UPDATE sessions SET status = 'failed', closed_at = NOW() WHERE id = %s",
            (sid,),
        )

        cursor.execute(
            """
            SELECT event_type
            FROM audit_events
            WHERE session_id = %s
              AND event_type IN ('session_status_transition', 'watermark_failed')
            ORDER BY id
            """,
            (sid,),
        )
        assert [row[0] for row in cursor.fetchall()] == [
            "session_status_transition",
            "watermark_failed",
        ]

    def test_session_noop_update_does_not_trigger_transition_audit(self, cursor):
        sid = str(uuid4())
        cursor.execute(
            """
            INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
            VALUES (
                %s,
                'a0eebc99-0000-0000-0000-000000000001',
                'a0eebc99-0000-0000-0000-000000000002',
                'a0eebc99-0000-0000-0000-000000000003',
                'psilocybin', 'active'
            );
            """,
            (sid,),
        )
        cursor.execute("UPDATE sessions SET status = 'active' WHERE id = %s", (sid,))

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM audit_events
            WHERE session_id = %s
              AND event_type IN (
                  'session_status_transition',
                  'watermark_verified',
                  'watermark_failed'
              )
            """,
            (sid,),
        )
        assert cursor.fetchone()[0] == 0

    def test_session_insert_triggers_audit(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
            VALUES (
                'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
                'a0eebc99-0000-0000-0000-000000000001',
                'a0eebc99-0000-0000-0000-000000000002',
                'a0eebc99-0000-0000-0000-000000000003',
                'psilocybin', 'initializing'
            ) ON CONFLICT (id) DO NOTHING;
        """)
        db_conn.commit()
        cursor.execute("""
            SELECT COUNT(*) FROM audit_events
            WHERE session_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11' AND table_name = 'sessions';
        """)
        assert cursor.fetchone()[0] >= 1, "Audit trigger did not fire on sessions INSERT"

    def test_echo_event_insert_triggers_audit(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO echo_events
                (session_id, participant_id, site_id, sponsor_id, event_type,
                 source, actor_id, actor_role, zone_label, lsl_timestamp)
            VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'zone_enter', 'manual_logging', 'C01', 'coordinator', 'in_room', 1234567890.0);
        """)
        db_conn.commit()
        cursor.execute("""
            SELECT COUNT(*) FROM audit_events
            WHERE session_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12'
            AND table_name = 'echo_events';
        """)
        assert cursor.fetchone()[0] >= 1, "Audit trigger did not fire on echo_events INSERT"

    def test_watchdog_process_restart_triggers_audit(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO alert_events (
                session_id, participant_id, site_id, sponsor_id,
                alert_type, compound, compound_dose, severity,
                algorithm_name, algorithm_version, algorithm_parameters,
                message
            ) VALUES (
                'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a14',
                'aaaa0000-0000-0000-0000-000000000001',
                'bbbb0000-0000-0000-0000-000000000001',
                'cccc0000-0000-0000-0000-000000000001',
                'process_restart', 'psilocybin', 25.0, 'warning',
                'watchdog', '1.0.0',
                '{"exit_code": 1, "restart_count": 1, "uptime_s": 42.0}'::jsonb,
                'lsl_forwarder exited with code 1, restarting (attempt 1/5)'
            );
        """)
        db_conn.commit()
        cursor.execute("""
            SELECT COUNT(*) FROM audit_events
            WHERE session_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a14'
              AND table_name = 'alert_events';
        """)
        assert cursor.fetchone()[0] >= 1, (
            "Audit trigger did not fire on watchdog process_restart INSERT"
        )
