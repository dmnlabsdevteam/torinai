#!/usr/bin/env python3
"""
Start TorinAI with Memory Monitoring
=====================================
Starts the autonomous system and monitors memory storage in real-time
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime
import time

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiomysql
import os
from dotenv import load_dotenv


# Load MySQL credentials
env_path = Path(__file__).parent.parent / ".env.mysql"
if env_path.exists():
    load_dotenv(env_path)

MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')


class MemoryMonitor:
    """Monitor memory_hot table in real-time"""

    def __init__(self):
        self.last_count = 0
        self.start_time = datetime.now()

    async def get_memory_count(self):
        """Get current memory count"""
        try:
            conn = await aiomysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                db="torinai_thinking_hot"
            )

            async with conn.cursor() as cursor:
                await cursor.execute("SELECT COUNT(*) FROM memory_hot")
                count = (await cursor.fetchone())[0]

            conn.close()
            return count

        except Exception as e:
            print(f"Error getting count: {e}")
            return None

    async def get_recent_memories(self, limit=5):
        """Get most recent memories"""
        try:
            conn = await aiomysql.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                db="torinai_thinking_hot"
            )

            async with conn.cursor() as cursor:
                await cursor.execute("""
                    SELECT memory_id, memory_type, content, importance_score, tags, created_at
                    FROM memory_hot
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (limit,))

                memories = await cursor.fetchall()

            conn.close()
            return memories

        except Exception as e:
            print(f"Error getting recent memories: {e}")
            return []

    async def monitor_loop(self):
        """Monitor memory storage"""
        print("="*80)
        print("Memory Storage Monitor")
        print("="*80)
        print(f"Started: {datetime.now().isoformat()}")
        print(f"Monitoring: torinai_thinking_hot.memory_hot")
        print("="*80)

        # Get initial count
        self.last_count = await self.get_memory_count() or 0
        print(f"\nInitial memory count: {self.last_count:,}")

        iteration = 0
        while True:
            await asyncio.sleep(5)  # Check every 5 seconds
            iteration += 1

            current_count = await self.get_memory_count()

            if current_count is None:
                continue

            new_memories = current_count - self.last_count

            if new_memories > 0:
                elapsed = (datetime.now() - self.start_time).total_seconds()
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] +{new_memories} new memories! (Total: {current_count:,}, Elapsed: {elapsed:.0f}s)")

                # Show recent memories
                recent = await self.get_recent_memories(new_memories)
                if recent:
                    print(f"\n  Recent Memories:")
                    for mem in recent:
                        memory_id, mem_type, content, importance, tags, created_at = mem
                        content_preview = content[:80] if content else "(no content)"
                        print(f"    - [{mem_type}] {content_preview}... (importance: {importance:.2f})")

                self.last_count = current_count

            elif iteration % 12 == 0:  # Every minute
                elapsed = (datetime.now() - self.start_time).total_seconds()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No new memories. Total: {current_count:,} (Elapsed: {elapsed:.0f}s)")


async def start_autonomous_system():
    """Start the autonomous coordinator"""
    print("\n" + "="*80)
    print("Starting Autonomous System")
    print("="*80)

    try:
        from core.agents.autonomous.autonomous_coordinator import create_autonomous_system

        coordinator = await create_autonomous_system()

        print("✓ Autonomous coordinator initialized")
        print("  - Extrinsic tasks should begin executing")
        print("  - Memories will be stored as tasks complete")
        print("  - Watch the monitor output below...")

        # Start the coordinator
        asyncio.create_task(coordinator.start())

        return True

    except Exception as e:
        print(f"❌ ERROR starting autonomous system: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main entry point"""
    print("\n" + "="*80)
    print("TorinAI System Startup with Memory Monitoring")
    print("="*80)
    print("\nThis script will:")
    print("  1. Start the autonomous coordinator")
    print("  2. Monitor memory_hot table for new entries")
    print("  3. Display new memories as they are created")
    print("\nPress Ctrl+C to stop\n")

    # Start autonomous system
    success = await start_autonomous_system()

    if not success:
        print("\n❌ Failed to start autonomous system")
        return

    # Start memory monitor
    monitor = MemoryMonitor()

    try:
        await monitor.monitor_loop()

    except KeyboardInterrupt:
        print("\n\n" + "="*80)
        print("Shutting down...")
        print("="*80)

        final_count = await monitor.get_memory_count()
        memories_created = final_count - monitor.last_count if final_count else 0
        elapsed = (datetime.now() - monitor.start_time).total_seconds()

        print(f"\nSession Summary:")
        print(f"  Duration: {elapsed:.0f} seconds")
        print(f"  Initial count: {monitor.last_count:,}")
        print(f"  Final count: {final_count:,}")
        print(f"  Memories created: {memories_created:,}")
        print(f"  Rate: {memories_created / (elapsed / 60):.2f} memories/minute")

        print("\n✓ Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
