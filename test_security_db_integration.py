#!/usr/bin/env python3
"""
Test Security Controller Database Integration
==============================================
Verify that SecurityController correctly writes to torinai_unified database
"""

import asyncio
import aiomysql
from pathlib import Path
import sys

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))

from core.security.controller import get_security_controller
from core.utils.env_loader import get_env


async def test_security_db_integration():
    """Test SecurityController database integration"""
    print("=" * 80)
    print("SECURITY CONTROLLER DATABASE INTEGRATION TEST")
    print("=" * 80)

    # 1. Get SecurityController instance
    print("\n1. Initializing SecurityController...")
    controller = get_security_controller()

    # Wait for database initialization
    await asyncio.sleep(2)

    # 2. Trigger some security events
    print("\n2. Triggering test security events...")

    # Event 1: SQL injection attempt
    controller._log_security_event('sql_injection_attempt', {
        'ip': '192.168.1.100',
        'payload': "' OR '1'='1",
        'endpoint': '/api/users'
    })

    # Event 2: Path traversal attempt
    controller._log_security_event('path_traversal_attempt', {
        'ip': '192.168.1.101',
        'path': '../../../etc/passwd',
        'endpoint': '/api/files'
    })

    # Event 3: Authentication failure
    controller._log_security_event('authentication_failed', {
        'ip': '192.168.1.102',
        'username': 'admin',
        'endpoint': '/api/login'
    })

    # Event 4: Audit log entry
    controller._audit_log('test_audit_action', {
        'test_data': 'verification_data'
    }, {
        'user_id': 'test_user_123',
        'ip': '127.0.0.1'
    })

    print("   ✅ 4 test events triggered")

    # Wait for async database writes to complete
    print("\n3. Waiting for database writes to complete...")
    await asyncio.sleep(3)

    # 4. Query database to verify
    print("\n4. Verifying data in database...")

    try:
        # Get database credentials
        db_host = get_env('MYSQL_HOST', 'localhost')
        db_port = int(get_env('MYSQL_PORT', '3306'))
        db_user = get_env('MYSQL_USER', 'root')
        db_password = get_env('MYSQL_PASSWORD', '')

        # Connect to database
        conn = await aiomysql.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            db='torinai_unified'
        )

        # Query security_events table
        async with conn.cursor() as cursor:
            await cursor.execute("""
                SELECT COUNT(*) FROM security_events
                WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 MINUTE)
            """)
            security_events_count = (await cursor.fetchone())[0]

            print(f"   security_events: {security_events_count} new rows")

            # Get recent security events
            await cursor.execute("""
                SELECT event_type, severity, source
                FROM security_events
                WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 MINUTE)
                ORDER BY timestamp DESC
                LIMIT 5
            """)
            recent_events = await cursor.fetchall()

            if recent_events:
                print("\n   Recent security events:")
                for event_type, severity, source in recent_events:
                    print(f"      - {event_type} ({severity}) from {source}")

        # Query security_logs table
        async with conn.cursor() as cursor:
            await cursor.execute("""
                SELECT COUNT(*) FROM security_logs
                WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 MINUTE)
            """)
            security_logs_count = (await cursor.fetchone())[0]

            print(f"\n   security_logs: {security_logs_count} new rows")

            # Get recent audit logs
            await cursor.execute("""
                SELECT event_type, severity, description
                FROM security_logs
                WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 MINUTE)
                ORDER BY timestamp DESC
                LIMIT 5
            """)
            recent_logs = await cursor.fetchall()

            if recent_logs:
                print("\n   Recent security logs:")
                for event_type, severity, description in recent_logs:
                    print(f"      - {event_type} ({severity}): {description}")

        conn.close()

        # 5. Summary
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)

        total_writes = security_events_count + security_logs_count

        checks = {
            'SecurityController initialized': controller.db_pool is not None,
            'Security events written to DB': security_events_count > 0,
            'Security logs written to DB': security_logs_count > 0,
            'Total database writes': total_writes >= 4
        }

        for check, passed in checks.items():
            status = "✅" if passed else "❌"
            if check == 'Total database writes':
                print(f"{status} {check}: {total_writes} rows")
            else:
                print(f"{status} {check}")

        passed = sum(checks.values())
        total = len(checks)
        print(f"\nPassed: {passed}/{total}")

        if passed == total:
            print("\n🎉 Database integration working correctly!")
        else:
            print(f"\n⚠️  {total - passed} check(s) failed")

    except Exception as e:
        print(f"\n❌ Error querying database: {e}")
        import traceback
        traceback.print_exc()

    # Cleanup
    await controller.cleanup()
    print("\n" + "=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(test_security_db_integration())
    except KeyboardInterrupt:
        print("\nTest cancelled by user")
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
