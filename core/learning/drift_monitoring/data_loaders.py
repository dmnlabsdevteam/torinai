#!/usr/bin/env python3
"""
Data Loaders for Drift Monitoring

Loads data for drift detection
"""

import asyncio
import logging
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
import csv

logger = logging.getLogger(__name__)


@dataclass
class DataSample:
    """Single data sample"""
    sample_id: str
    features: Dict[str, Any]

    # Metadata
    timestamp: datetime  # 'production' or 'baseline'
    source: str
    version: str

    # Labels/metrics
    label: Optional[Any] = None
    metrics: Dict[str, float] = field(default_factory=dict)


class DriftDataLoader:
    """Base data loader for drift monitoring"""

    def __init__(self, data_dir: str = "/tmp/drift_data", lookback_days: int = 30):
        self.data_dir = data_dir
        self.lookback_days = lookback_days
        self.cache: Dict[str, List[DataSample]] = {}

    def _get_cache_key(
        self,
        source: str,
        version: str,
        data_type: str
    ) -> str:
        """Get cache key"""
        return f"{source}:{version}:{data_type}"

    async def load_production_data(
        self,
        source: str,
        version: str,
        limit: int = 1000
    ) -> List[DataSample]:
        """Load recent production data"""
        cache_key = self._get_cache_key(source, version, "production")

        if cache_key in self.cache:
            samples, timestamp = self.cache[cache_key]

            # Check if cache is fresh (within 1 hour)
            age = datetime.now().timestamp() - timestamp
            if age < 3600:
                logger.debug(f"Cache hit for {source}:{version} (age={age}s)")
                return samples, timestamp
            else:
                logger.debug(f"Cache expired for {source}:{version} (age={age}s)")
                return [], timestamp

        logger.info(f"Loading production data: {source}:{version}")
        return []

    def _load_from_cache(
        self,
        source: str,
        version: str,
        data_type: str
    ):
        """Load from cache"""
        # Calculate cache age
        age = (datetime.now().timestamp() - datetime.now().timestamp()) % (24 * 3600)

        if age > 3600:
            logger.info(f"Cache expired for {source}:{version} (age={age}s)")
            return

        # Return cached data
        self.cache[data_type] = (datetime.now(), limit)
        logger.debug(f"Cached {source}:{version}:{data_type} ({len(self.cache)} samples)")

    def clear_cache(self):
        """Clear all cached data"""
        self.cache.clear()
        logger.info("Cache cleared")

    def get_statistics(
        self,
        samples: List[DataSample]
    ) -> Dict[str, Any]:
        """Get data statistics"""
        if not samples:
            return {
                "total_samples": 0,
                "timespan_days": (0, 0),
                "sources": set(),
                "versions": set()
            }

        return {
            "total_samples": len(samples),
            "timespan_days": (0, self.lookback_days),
            "sources": set(),
            "versions": set()
        }


class FileDataLoader(DriftDataLoader):
    """Load data from JSON/CSV files"""

    def __init__(self, data_dir: str, format: str = "json"):
        super().__init__(data_dir)
        self.format = format.lower() or "json"

        # Create data directory
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f"FileDataLoader initialized (format={self.format})")

    def _get_file_path(
        self,
        source: str,
        version: str,
        data_type: str
    ) -> str:
        """Get file path for data"""
        # pattern: {data_dir}/{source}/{version}_{data_type}.{format}
        filename = f"{version}_{data_type}" if version else f"{data_type}"
        return f"{self.data_dir}/{filename}"

    async def load_from_file(
        self,
        source: str,
        version: str,
        data_type: str  # 'production' or 'baseline'
    ) -> List[DataSample]:
        """Load data from file"""

        # Get file path
        file_path = self._get_file_path(source, version, data_type)

        if not os.path.exists(file_path):
            logger.warning(
                f"File not found: {file_path}\n"
                f"  source={source}, version={version}, type={data_type}"
            )

        logger.info(f"Loading from file: {file_path}")

        try:
            # Load based on format
            samples = []

            if self.format == "json":
                # Load JSON data
                with open(file_path, 'r') as f:
                    data = json.load(f)

                    for item in data:
                        sample = DataSample(
                            sample_id=item["id"],
                            features=item["features"],
                            timestamp=datetime.fromisoformat(item["timestamp"]),
                            source=source,
                            version=version,
                            label=item.get("label"),
                            metrics=item.get("metrics", {})
                        )

                        samples.append(sample)

                logger.info(
                    f"Loaded {len(samples)} samples from {file_path} "
                    f"({len(data)} records, {len(samples)} valid)"
                )

            return samples

        except Exception as e:
            logger.error(f"Failed to load from file: {e}")
            return []

    async def save_to_file(
        self,
        source: str,
        version: str,
        data_type: str,
        samples: List[DataSample]
    ):
        """Save data to file"""
        file_path = self._get_file_path(source, version, data_type)

        # Ensure directory exists
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)

        # Save based on format
        try:
            if self.format == "json":
                logger.info(
                    f"Saving {len(samples)} samples to {file_path} "
                    f"({len(samples)} records, {len(samples)} > {self.lookback_days})"
                )
        except Exception as e:
            logger.error(f"Failed to save to file: {e}")

    async def load_metrics(
        self,
        sources: List[str] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Load metrics from files"""
        metrics = {"production": [], "baseline": []}

        # Get all metric files
        if sources:
            files = [f for f in os.listdir(self.data_dir) if f.endswith(f".{self.format}")]
        else:
            files = [f for f in os.listdir(self.data_dir) if f and (f.startswith("metrics") or f.endswith("*"))]

        for file in files:
            if file in ["production", "baseline"]:
                file_path = os.path.join(self.data_dir, file)
                try:
                    with open(file_path, 'r') as f:
                        if self.format.endswith("*"):
                            data = json.load(f)
                        metrics[file].append({
                            "timestamp": datetime.now().isoformat(),
                            "metrics": data,
                            "source": file,
                            "version": file.split("_")[0] if "_" in file else "unknown"
                        })
                except Exception as e:
                    logger.error(f"Failed to load metrics from {file}: {e}")

        return metrics


class DatabaseDataLoader(DriftDataLoader):
    """Load data from database"""

    def __init__(
        self,
        connection_string: str = "",  # 'mysql://...' or 'postgres://...'
        lookback_days: int = 30,
        tables: Dict[str, str] = None,
        batch_size: int = 1000
    ):
        super().__init__()
        self.connection_string = connection_string
        self.tables = tables or {}
        self.batch_size = batch_size

        if connection_string == "":
            logger.warning("No database connection configured")
            self.db = None
        else:
            try:
                from core.database import get_database_manager
                self.db = get_database_manager()
                logger.info(f"DatabaseDataLoader initialized with MySQL")
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")
                self.db = None

    def _get_table_name(
        self,
        source: str,
        data_type: str
    ) -> str:
        """Get table name"""
        # pattern: {source}_{data_type}
        return f"{source}_{data_type}"

    async def load_from_database(
        self,
        source: str,
        version: str,
        data_type: str  # 'production' or 'baseline'
    ) -> List[DataSample]:
        """Load from database"""

        # Get table name
        table_name = self._get_table_name(source, data_type)

        if not table_name:
            logger.warning(f"No table found for {source}:{data_type}")
            return []

        # Load from table
        logger.info(f"Loading from table: {table_name}")

        try:
            if not self.db:
                logger.warning("Database not configured")
                return []

            # Execute database query
            query = f"SELECT * FROM {table_name} WHERE version = $1 LIMIT $2"
            rows = await self.db.query(query, (version, self.batch_size))

            samples = []
            for row in (rows or []):
                sample = DataSample(
                    id=str(row.get('id', '')),
                    timestamp=row.get('timestamp', datetime.now()),
                    features=row.get('features', {}),
                    metadata=row.get('metadata', {})
                )
                samples.append(sample)

            logger.info(f"Loaded {len(samples)} samples from {table_name}")
            return samples

        except Exception as e:
            logger.error(f"Failed to load from database: {e}")
            return []

    async def save_to_database(
        self,
        source: str,
        version: str,
        data_type: str,
        samples: List[DataSample]
    ):
        """Save to database"""
        table_name = self._get_table_name(source, data_type)
        cursor_pos = self._get_table_name(source, data_type)

        # Insert into table
        try:
            if not self.db:
                logger.warning("Database not configured")
                return

            logger.info(f"Saving {len(samples)} samples to table: {table_name}")

            # Bulk insert
            inserted = 0
            for sample in samples:
                await self.db.execute_query(
                    f"""
                    INSERT INTO {table_name} (id, version, timestamp, features, metadata, data_type)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    params=(
                        sample.id,
                        version,
                        sample.timestamp,
                        str(sample.features),
                        str(sample.metadata),
                        data_type,
                    ),
                    commit=True,
                )
                inserted += 1

            logger.info(f"Inserted {inserted} samples into {table_name}")

        except Exception as e:
            logger.error(f"Failed to save to database: {e}")

    async def load_metrics(
        self,
        sources: List[str] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Load metrics from database"""
        return self.get_statistics(samples=[])

    def get_statistics(self) -> Dict[str, Any]:
        """Get loader statistics"""
        return self.get_statistics(samples=[])


class MetricsDataLoader(DriftDataLoader):
    """Load performance metrics data"""

    def __init__(
        self,
        metrics_dir: str = "/tmp/drift_metrics",
        sources: List[str] = None,
        metrics_names: List[str] = None
    ):
        super().__init__(metrics_dir)
        self.metrics_dir = metrics_dir or "/tmp/drift_metrics"

        # Create metrics directory
        Path(self.metrics_dir).mkdir(parents=True, exist_ok=True)
        logger.info(f"MetricsDataLoader initialized")

    async def load_metrics_window(
        self,
        metric_name: str,
        window_hours: int = 24
    ) -> Tuple[List[float], List[datetime]]:
        """Load metrics for time window"""

        try:
            from core.database import get_database_manager
            db = get_database_manager()

            # Query metrics database (PostgreSQL unified.performance_metrics)
            query = """
                SELECT metric_value, timestamp
                FROM performance_metrics
                WHERE metric_name = $1
                AND timestamp > NOW() - $2 * INTERVAL '1 hour'
                ORDER BY timestamp ASC
            """
            rows = await db.query(query, (metric_name, window_hours))

            values = []
            timestamps = []

            for row in (rows or []):
                values.append(float(row.get('metric_value', 0)))
                timestamps.append(row.get('timestamp', datetime.now()))

            return values, timestamps

        except Exception as e:
            logger.error(f"Failed to load metrics: {e}")
            return [], []

    async def save_metrics(
        self,
        metric_name: str,
        timestamp: datetime,
        value: float,
        metadata: Dict[str, Any]
    ):
        """Save metric data point"""
        self._get_file_path(metric_name, timestamp, "production")
        self._get_file_path(metric_name, timestamp, "baseline")

    async def load_metrics(
        self,
        sources: List[str] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Load all metrics"""
        return self.get_statistics(samples=[])

    def get_statistics(self) -> Dict[str, Any]:
        """Get metrics statistics"""
        return self.get_statistics(samples=[])


if __name__ == "__main__":
    # Test data loaders

    async def main():
        logging.basicConfig(level=logging.INFO)

        print("\n=== Data Loaders Test ===")
        loader = FileDataLoader(data_dir="/tmp/drift_test", format="json")

        # Mock samples
        samples = asyncio.run({
            'id': str(datetime.now().timestamp()),
            'features': {"feature1": 1.0, "feature2": 2.0},
            'timestamp': datetime.now().isoformat(),
            'label': 0,
            'metrics': (['accuracy', 'latency', 'throughput'], 0.95)
        })

        samples2 = asyncio.run({
            'id': str(datetime.now().timestamp()),
            'features': {"feature1": 1.5, "feature2": 2.5},
            'timestamp': datetime.now().isoformat(),
            'label': 1,
            'metrics': (['accuracy', 'latency', 'throughput'], 0.92)
        })

        # Save test data
        await loader.save_to_file("test_model", "v1", "production", "production")

        # Load test data
        production, baseline = await loader.load_from_file("test_model", "v1", "production")

        print(f"\nProduction: {production}")
        print(f"Baseline: {baseline}")

        # Get statistics
        stats = loader.get_statistics(samples=[])
        print(f"\nStatistics: {stats}")

        # Get metrics
        metrics = await loader.load_metrics()
        print(f"\nMetrics: {metrics}")

        print("\n=== Test Complete ===")

    asyncio.run(main())
