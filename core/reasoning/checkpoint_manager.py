#!/usr/bin/env python3
"""
Checkpoint Manager
============================
Save and restore reasoning state for recovery

Purpose:
- Save reasoning checkpoints (~7% compression)
- Restore from checkpoints
- Automatic cleanup
- State recovery

Features:
- Incremental checkpointing
- Compressed storage
- Automatic pruning
- Fast recovery
"""

from core.capability import raise_if_structural
import asyncio
import logging
import json
import gzip
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """Reasoning checkpoint"""
    checkpoint_id: str
    timestamp: datetime
    state: Dict[str, Any]  # (reasoning, context)
    compressed: bool = True

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    size_bytes: int = 0
    compressed_size: int = 0

    # Reasoning state
    reasoning_step: int = 0
    total_steps: int = 0
    progress_percent: float = 0.0

    # Success markers (for pruning, only keep successful checkpoints)
    success: bool = False
    error: Optional[str] = None
    recovery_count: int = 0


class CheckpointManager:
    """
    Checkpoint Manager

    Purpose:
    - Save reasoning state at intervals
    - Enable recovery from failures
    - Automatic cleanup of old checkpoints
    """

    def __init__(self,
                 checkpoint_dir: str = "data/checkpoints",
                 max_checkpoints: int = 7,
                 compression_enabled: bool = True):
        """
        Initialize checkpoint manager

        Args:
            checkpoint_dir: Directory to store checkpoints
            max_checkpoints: Maximum checkpoints to keep (default 7 = 7%)
            compression_enabled: Enable compression (default = True, ~7% size)
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.max_checkpoints = max_checkpoints
        self.compression_enabled = compression_enabled

        # Ensure directory exists
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # Cache
        self.checkpoints: Dict[str, Checkpoint] = {}

        # Statistics
        self.stats = {
            'total_saved': 0,
            'total_loaded': 0,
            'total_pruned': 0
        }

        logger.info(
            f"CheckpointManager initialized: "
            f"dir={checkpoint_dir}, "
            f"max={max_checkpoints}, "
            f"compression={compression_enabled}"
        )

    async def save_checkpoint(
        self,
        checkpoint_id: str,
        state: Dict[str, Any]
    ) -> bool:
        """
        Save a checkpoint

        Args:
            checkpoint_id: Unique identifier
            state: State to save (reasoning, context, etc.)

        Returns:
            Success boolean
        """
        try:
            # Create checkpoint
            checkpoint = Checkpoint(
                checkpoint_id=checkpoint_id,
                timestamp=datetime.now(),
                state=state,
                compressed=self.compression_enabled
            )

            # Add metadata
            checkpoint.metadata['created_at'] = checkpoint.timestamp.isoformat()
            checkpoint.metadata['compression'] = self.compression_enabled

            # Serialize
            data = {
                'checkpoint_id': checkpoint.checkpoint_id,
                'timestamp': checkpoint.timestamp.isoformat(),
                'state': checkpoint.state,
                'metadata': checkpoint.metadata
            }

            # Convert to JSON
            json_data = json.dumps(data, indent=2)
            checkpoint.size_bytes = len(json_data.encode('utf-8'))

            # Compress if enabled
            if self.compression_enabled:
                compressed = gzip.compress(json_data.encode('utf-8'))
                checkpoint.compressed_size = len(compressed)
                file_data = compressed
                file_ext = '.json.gz'
            else:
                file_data = json_data.encode('utf-8')
                file_ext = '.json'

            # Write to file
            file_path = self.checkpoint_dir / f"{checkpoint_id}{file_ext}"
            with open(file_path, 'wb') as f:
                f.write(file_data)

            # Cache checkpoint
            self.checkpoints[checkpoint_id] = checkpoint

            # Update stats
            self.stats['total_saved'] += 1

            # Prune old checkpoints
            await self._prune_checkpoints()

            logger.info(
                f"✓ Checkpoint saved: {checkpoint_id} "
                f"({checkpoint.size_bytes} → {checkpoint.compressed_size} bytes)"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to save checkpoint {checkpoint_id}: {e}")
            return False

    async def load_checkpoint(
        self,
        checkpoint_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Load a checkpoint

        Args:
            checkpoint_id: Checkpoint identifier

        Returns:
            Checkpoint state or None if not found
        """
        try:
            # Check if cached
            if checkpoint_id in self.checkpoints:
                # COUNTED HERE TOO. This early return used to skip the stat
                # below, so a checkpoint served from cache was a load that
                # never happened as far as `get_statistics()` was concerned --
                # and because `save_checkpoint` populates the cache, the common
                # case (save then restore in one process) reported
                # total_loaded=0 forever. health_monitor reads exactly that
                # number, so "restore has never been exercised" was
                # indistinguishable from "restore works and is warm".
                logger.info(f"Loading from cache: {checkpoint_id}")
                self.stats['total_loaded'] += 1
                return self.checkpoints[checkpoint_id].state

            # Try to load from file
            file_path_gz = self.checkpoint_dir / f"{checkpoint_id}.json.gz"
            file_path_json = self.checkpoint_dir / f"{checkpoint_id}.json"

            file_path = None
            is_compressed = False

            if file_path_gz.exists():
                file_path = file_path_gz
                is_compressed = True
            elif file_path_json.exists():
                file_path = file_path_json
                is_compressed = False

            if not file_path:
                logger.warning(f"Checkpoint not found: {checkpoint_id}")
                return None

            # Read file
            with open(file_path, 'rb') as f:
                file_data = f.read()

            # Decompress if needed
            if is_compressed:
                json_data = gzip.decompress(file_data).decode('utf-8')
            else:
                json_data = file_data.decode('utf-8')

            # Parse JSON
            data = json.loads(json_data)

            # Create checkpoint object
            checkpoint = Checkpoint(
                checkpoint_id=data['checkpoint_id'],
                timestamp=datetime.fromisoformat(data['timestamp']),
                state=data['state'],
                metadata=data.get('metadata', {}),
                compressed=is_compressed
            )

            # Cache
            self.checkpoints[checkpoint_id] = checkpoint

            # Update stats
            self.stats['total_loaded'] += 1

            logger.info(f"✓ Checkpoint loaded: {checkpoint_id}")

            return checkpoint.state

        except Exception as e:
            logger.error(f"Failed to load checkpoint {checkpoint_id}: {e}")
            return None

    async def list_checkpoints(self) -> List[str]:
        """List all available checkpoints"""
        try:
            checkpoints = []

            # List files in checkpoint directory
            for file_path in self.checkpoint_dir.glob("*.json*"):
                # Extract checkpoint ID from filename
                checkpoint_id = file_path.stem.replace('.json', '')
                checkpoints.append(checkpoint_id)

            return sorted(checkpoints)

        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'checkpoint_manager.list_checkpoints')
            logger.error(f"Failed to list checkpoints: {e}")
            return []

    async def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a specific checkpoint"""
        try:
            # Remove from cache
            if checkpoint_id in self.checkpoints:
                del self.checkpoints[checkpoint_id]

            # Remove file
            file_path_gz = self.checkpoint_dir / f"{checkpoint_id}.json.gz"
            file_path_json = self.checkpoint_dir / f"{checkpoint_id}.json"

            deleted = False
            if file_path_gz.exists():
                file_path_gz.unlink()
                deleted = True

            if file_path_json.exists():
                file_path_json.unlink()
                deleted = True

            if deleted:
                logger.info(f"Deleted checkpoint: {checkpoint_id}")

            return deleted

        except Exception as e:
            logger.error(f"Failed to delete checkpoint {checkpoint_id}: {e}")
            return False

    async def _prune_checkpoints(self):
        """Prune old checkpoints to stay within max_checkpoints limit"""
        try:
            checkpoints = await self.list_checkpoints()

            if len(checkpoints) <= self.max_checkpoints:
                return

            # Sort by modification time (oldest first)
            checkpoint_files = []
            for checkpoint_id in checkpoints:
                file_path_gz = self.checkpoint_dir / f"{checkpoint_id}.json.gz"
                file_path_json = self.checkpoint_dir / f"{checkpoint_id}.json"

                file_path = file_path_gz if file_path_gz.exists() else file_path_json
                if file_path.exists():
                    mtime = file_path.stat().st_mtime
                    checkpoint_files.append((mtime, checkpoint_id))

            # Sort by modification time
            checkpoint_files.sort()

            # Delete oldest checkpoints
            num_to_delete = len(checkpoints) - self.max_checkpoints
            for _, checkpoint_id in checkpoint_files[:num_to_delete]:
                await self.delete_checkpoint(checkpoint_id)
                self.stats['total_pruned'] += 1

            logger.info(f"Pruned {num_to_delete} old checkpoints")

        except Exception as e:
            logger.error(f"Failed to prune checkpoints: {e}")

    async def clear_all_checkpoints(self) -> int:
        """Clear all checkpoints"""
        try:
            checkpoints = await self.list_checkpoints()
            count = 0

            for checkpoint_id in checkpoints:
                if await self.delete_checkpoint(checkpoint_id):
                    count += 1

            self.checkpoints.clear()
            logger.info(f"Cleared {count} checkpoints")

            return count

        except Exception as e:
            logger.error(f"Failed to clear checkpoints: {e}")
            return 0

    async def get_latest_checkpoint(self) -> Optional[str]:
        """Get the most recent checkpoint ID"""
        try:
            checkpoints = await self.list_checkpoints()

            if not checkpoints:
                return None

            # Find newest by modification time
            newest_checkpoint = None
            newest_time = 0

            for checkpoint_id in checkpoints:
                file_path_gz = self.checkpoint_dir / f"{checkpoint_id}.json.gz"
                file_path_json = self.checkpoint_dir / f"{checkpoint_id}.json"

                file_path = file_path_gz if file_path_gz.exists() else file_path_json
                if file_path.exists():
                    mtime = file_path.stat().st_mtime
                    if mtime > newest_time:
                        newest_time = mtime
                        newest_checkpoint = checkpoint_id

            return newest_checkpoint

        except Exception as e:
            logger.error(f"Failed to get latest checkpoint: {e}")
            return None

    async def get_statistics(self) -> Dict[str, Any]:
        """Get checkpoint statistics"""
        checkpoints = await self.list_checkpoints()

        return {
            'total_checkpoints': len(checkpoints),
            'total_saved': self.stats['total_saved'],
            'total_loaded': self.stats['total_loaded'],
            'total_pruned': self.stats['total_pruned'],
            'max_checkpoints': self.max_checkpoints,
            'compression_enabled': self.compression_enabled
        }

    async def restore_from_latest(self) -> Optional[Dict[str, Any]]:
        """Restore from the latest checkpoint"""
        latest = await self.get_latest_checkpoint()

        if not latest:
            logger.warning("No checkpoints available for restore")
            return None

        logger.info(f"Restoring from latest checkpoint: {latest}")
        return await self.load_checkpoint(latest)


# Singleton instance
_checkpoint_manager = None


def get_checkpoint_manager() -> CheckpointManager:
    """Get global checkpoint manager instance"""
    global _checkpoint_manager
    if _checkpoint_manager is None:
        _checkpoint_manager = CheckpointManager()
    return _checkpoint_manager


# CLI test
async def main():
    """Test checkpoint manager"""
    logging.basicConfig(level=logging.INFO)

    manager = get_checkpoint_manager()

    print("\n=== Checkpoint Manager Test ===")

    # Save a checkpoint
    test_state = {
        'reasoning_step': 5,
        'context': 'test context',
        'variables': {'x': 10, 'y': 20}
    }

    success = await manager.save_checkpoint("test_checkpoint_001", test_state)
    print(f"Save checkpoint: {success}")

    # Load checkpoint
    loaded = await manager.load_checkpoint("test_checkpoint_001")
    print(f"Loaded state: {loaded}")

    # List checkpoints
    checkpoints = await manager.list_checkpoints()
    print(f"Available checkpoints: {checkpoints}")

    # Get statistics
    stats = await manager.get_statistics()
    print(f"Statistics: {stats}")

    # Cleanup
    await manager.clear_all_checkpoints()


if __name__ == "__main__":
    asyncio.run(main())
