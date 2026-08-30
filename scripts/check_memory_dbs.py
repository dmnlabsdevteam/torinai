#!/usr/bin/env python3
"""
Check torinai_thinking_hot and torinai_memory_cold databases ONLY
"""
import asyncio
import aiomysql
import os
from pathlib import Path
from dotenv import load_dotenv

# Load MySQL credentials
env_path = Path(__file__).parent.parent / ".env.mysql"
if env_path.exists():
    load_dotenv(env_path)

MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')


async def check_database(db_name: str):
    """Check a single database"""
    print(f"\n{'=' * 80}")
    print(f"DATABASE: {db_name}")
    print(f"{'=' * 80}\n")

    try:
        conn = await aiomysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            db=db_name
        )

        async with conn.cursor() as cursor:
            # Get all tables
            await cursor.execute("SHOW TABLES")
            tables = await cursor.fetchall()
            table_names = [table[0] for table in tables]

            if not table_names:
                print(f"⚠️  Database '{db_name}' exists but contains NO TABLES\n")
                conn.close()
                return

            print(f"✓ Found {len(table_names)} table(s):\n")

            # Get row counts and schemas
            for table_name in table_names:
                # Row count
                await cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                result = await cursor.fetchone()
                row_count = result[0] if result else 0

                print(f"\nTable: {table_name}")
                print(f"  Rows: {row_count:,}")

                # Schema
                await cursor.execute(f"DESCRIBE {table_name}")
                schema = await cursor.fetchall()

                print(f"  Schema:")
                for field, field_type, null, key, default, extra in schema:
                    key_str = f" [{key}]" if key else ""
                    extra_str = f" {extra}" if extra else ""
                    print(f"    - {field}: {field_type}{key_str}{extra_str}")

        conn.close()

    except Exception as e:
        print(f"❌ Error accessing database '{db_name}': {e}\n")


async def main():
    """Main function"""

    print("=" * 80)
    print("Memory Database Schema Check")
    print("=" * 80)

    # Check both databases
    await check_database("torinai_thinking_hot")
    await check_database("torinai_memory_cold")

    # Expected schemas
    print(f"\n{'=' * 80}")
    print("EXPECTED SCHEMAS")
    print(f"{'=' * 80}\n")

    print("torinai_thinking_hot should have:")
    print("  - memories (main memory storage)")
    print("  - memory_tags (tag associations)")
    print("  - archive_log (tracking archived memories)")

    print("\ntorinai_memory_cold should have:")
    print("  - Either R2-based (no MySQL tables)")
    print("  - OR if using MySQL: archived_memories table")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
