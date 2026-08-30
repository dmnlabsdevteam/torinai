#!/usr/bin/env python3
"""
Database Schema Diagnostic Tool
Checks all TorinAI databases and reports their schemas
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


async def get_tables_in_database(db_name: str) -> list:
    """Get all tables in a database"""
    try:
        conn = await aiomysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            db=db_name
        )

        async with conn.cursor() as cursor:
            await cursor.execute("SHOW TABLES")
            tables = await cursor.fetchall()
            conn.close()
            return [table[0] for table in tables]
    except Exception as e:
        print(f"Error accessing database '{db_name}': {e}")
        return None


async def get_table_schema(db_name: str, table_name: str) -> list:
    """Get schema for a specific table"""
    try:
        conn = await aiomysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            db=db_name
        )

        async with conn.cursor() as cursor:
            await cursor.execute(f"DESCRIBE {table_name}")
            schema = await cursor.fetchall()
            conn.close()
            return schema
    except Exception as e:
        print(f"Error getting schema for '{db_name}.{table_name}': {e}")
        return None


async def get_table_row_count(db_name: str, table_name: str) -> int:
    """Get number of rows in a table"""
    try:
        conn = await aiomysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            db=db_name
        )

        async with conn.cursor() as cursor:
            await cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            result = await cursor.fetchone()
            conn.close()
            return result[0] if result else 0
    except Exception as e:
        print(f"Error counting rows in '{db_name}.{table_name}': {e}")
        return 0


async def check_all_databases():
    """Main diagnostic function"""

    print("=" * 80)
    print("TorinAI Database Schema Diagnostic Report")
    print("=" * 80)
    print()

    # Databases to check
    databases = [
        ("torinai_unified", "Main unified database (directives, governance, metrics, test logs, chaos experiments)"),
        ("torinai_thinking_hot", "Hot tier memory storage (last 60 days)"),
        ("torinai_memory_cold", "Cold tier memory storage (60+ days old, if MySQL)"),
    ]

    for db_name, description in databases:
        print(f"\n{'=' * 80}")
        print(f"DATABASE: {db_name}")
        print(f"Description: {description}")
        print(f"{'=' * 80}\n")

        tables = await get_tables_in_database(db_name)

        if tables is None:
            print(f"❌ Database '{db_name}' does not exist or is not accessible\n")
            continue

        if not tables:
            print(f"⚠️  Database '{db_name}' exists but contains NO TABLES\n")
            continue

        print(f"✓ Found {len(tables)} table(s):\n")

        # Table summary
        table_summary = []
        for table_name in tables:
            row_count = await get_table_row_count(db_name, table_name)
            table_summary.append([table_name, row_count])

        # Print table summary
        print(f"{'Table Name':<40} {'Row Count':>15}")
        print("-" * 60)
        for table_name, row_count in table_summary:
            print(f"{table_name:<40} {row_count:>15,}")
        print()

        # Detailed schema for each table
        print(f"\nDetailed Schema Information:")
        print("-" * 80)
        for table_name in tables:
            print(f"\nTable: {db_name}.{table_name}")
            schema = await get_table_schema(db_name, table_name)
            if schema:
                print(f"  {'Field':<30} {'Type':<20} {'Null':<6} {'Key':<6} {'Default':<15} {'Extra':<15}")
                print("  " + "-" * 100)
                for field, field_type, null, key, default, extra in schema:
                    print(f"  {field:<30} {field_type:<20} {null:<6} {key:<6} {str(default or ''):<15} {str(extra or ''):<15}")
            print()

    # Expected schema vs actual schema
    print("\n" + "=" * 80)
    print("SCHEMA VALIDATION REPORT")
    print("=" * 80 + "\n")

    print("Expected Tables:")
    print("-" * 80)

    # torinai_unified expected tables
    unified_expected = [
        "governance_laws",
        "internal_directives",
        "directive_applications",
        "directive_evolution_log",
        "directive_governance_evaluations",
        "directive_ab_tests",
        "test_sessions",
        "test_results",
        "operation_logs",
        "chaos_experiments",
        "chaos_metrics",
        "chaos_events",
        "governance_sessions",  # For governance dashboard
        "notifications"  # For notifications dashboard
    ]

    # torinai_thinking_hot expected tables
    hot_expected = [
        "memories",
        "memory_tags",
        "archive_log"
    ]

    # Check torinai_unified
    unified_tables = await get_tables_in_database("torinai_unified")
    print("\ntorinai_unified:")
    if unified_tables is not None:
        for expected in unified_expected:
            status = "✓" if expected in unified_tables else "✗ MISSING"
            print(f"  {status} {expected}")

        # Check for unexpected tables
        unexpected = set(unified_tables) - set(unified_expected)
        if unexpected:
            print(f"\n  ⚠️  Unexpected tables in torinai_unified:")
            for table in unexpected:
                print(f"      - {table}")
    else:
        print("  ❌ Database does not exist")

    # Check torinai_thinking_hot
    hot_tables = await get_tables_in_database("torinai_thinking_hot")
    print("\ntorinai_thinking_hot:")
    if hot_tables is not None:
        for expected in hot_expected:
            status = "✓" if expected in hot_tables else "✗ MISSING"
            print(f"  {status} {expected}")

        # Check for unexpected tables
        unexpected = set(hot_tables) - set(hot_expected)
        if unexpected:
            print(f"\n  ⚠️  Unexpected tables in torinai_thinking_hot:")
            for table in unexpected:
                print(f"      - {table}")
    else:
        print("  ❌ Database does not exist")

    # Check if tables from unified ended up in hot tier (common mistake)
    if unified_tables and hot_tables:
        misplaced_in_hot = set(unified_expected) & set(hot_tables)
        if misplaced_in_hot:
            print(f"\n❌ ERROR: Tables that belong in torinai_unified found in torinai_thinking_hot:")
            for table in misplaced_in_hot:
                print(f"      - {table}")
            print("\n   These tables should be DROPPED from torinai_thinking_hot and exist only in torinai_unified")

    print("\n" + "=" * 80)
    print("END OF DIAGNOSTIC REPORT")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(check_all_databases())
    except KeyboardInterrupt:
        print("\nDiagnostic cancelled by user")
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
