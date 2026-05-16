"""Tests for audit triggers firing on INSERT into key tables."""


class TestAuditTriggers:
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
                 source, actor_id, zone_label, lsl_timestamp)
            VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'zone_enter', 'manual_logging', 'C01', 'in_room', 1234567890.0);
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
