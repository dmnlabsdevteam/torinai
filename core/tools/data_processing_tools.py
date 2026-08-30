#!/usr/bin/env python3
"""
Data Processing Tools
====================
Tools for data manipulation, transformation, and analysis

Tools:
- parse_json: Parse JSON with error handling
- parse_yaml: Parse YAML
- parse_csv: Parse CSV files
- convert_format: Convert between formats
- transform_data: Apply transformations
- aggregate_data: Aggregate/summarize data
- merge_datasets: Merge multiple datasets
- filter_data: Filter data by criteria
- sort_data: Sort data
- deduplicate_data: Remove duplicates

Author: Torin AI Team
"""

import logging
import json
import csv
import re
import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata


logger = logging.getLogger(__name__)


class ParseJSONTool(Tool):
    """Parse JSON with error handling"""

    def __init__(self):
        super().__init__()
        self.name = "parse_json"
        self.description = "Parse JSON string or file with detailed error handling"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="input",
                type="string",
                description="JSON string or file path",
                required=True
            ),
            ToolParameter(
                name="is_file",
                type="boolean",
                description="Whether input is a file path",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="parse_json",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.PARSE_DATA,
                    description="Parse JSON data"
                )
            ]
        )

    async def execute(self, input: str, is_file: bool = False) -> ToolResult:
        try:
            # Auto-detect file path (check if file exists or looks like a path)
            should_try_file = is_file or ('/' in input or '\\' in input)

            if should_try_file:
                try:
                    file_path = Path(input).expanduser().resolve()
                    if file_path.exists():
                        with open(file_path, 'r') as f:
                            data = json.load(f)
                        return ToolResult(
                            success=True,
                            output={
                                'data': data,
                                'type': type(data).__name__,
                                'size': len(json.dumps(data)),
                                'source': 'file'
                            }
                        )
                except:
                    pass  # Fall through to string parsing

            # Try parsing as JSON string
            data = json.loads(input)
            return ToolResult(
                success=True,
                output={
                    'data': data,
                    'type': type(data).__name__,
                    'size': len(json.dumps(data)),
                    'source': 'string'
                }
            )

        except json.JSONDecodeError as e:
            return ToolResult(success=False, output=None, error=f"JSON parse error: {e}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ParseYAMLTool(Tool):
    """Parse YAML"""

    def __init__(self):
        super().__init__()
        self.name = "parse_yaml"
        self.description = "Parse YAML string or file"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="input",
                type="string",
                description="YAML string or file path",
                required=True
            ),
            ToolParameter(
                name="is_file",
                type="boolean",
                description="Whether input is a file path",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="parse_yaml",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.PARSE_DATA,
                    description="Parse YAML data"
                )
            ]
        )

    async def execute(self, input: str, is_file: bool = False) -> ToolResult:
        try:
            import yaml

            # Auto-detect file path (check if file exists or looks like a path)
            should_try_file = is_file or ('/' in input or '\\' in input)

            if should_try_file:
                try:
                    file_path = Path(input).expanduser().resolve()
                    if file_path.exists():
                        with open(file_path, 'r') as f:
                            data = yaml.safe_load(f)
                        return ToolResult(
                            success=True,
                            output={
                                'data': data,
                                'type': type(data).__name__,
                                'source': 'file'
                            }
                        )
                except:
                    pass  # Fall through to string parsing

            # Try parsing as YAML string
            data = yaml.safe_load(input)
            return ToolResult(
                success=True,
                output={
                    'data': data,
                    'type': type(data).__name__,
                    'source': 'string'
                }
            )

        except yaml.YAMLError as e:
            return ToolResult(success=False, output=None, error=f"YAML parse error: {e}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ParseCSVTool(Tool):
    """Parse CSV files"""

    def __init__(self):
        super().__init__()
        self.name = "parse_csv"
        self.description = "Parse CSV file and return data as list of dictionaries"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to CSV file",
                required=True
            ),
            ToolParameter(
                name="delimiter",
                type="string",
                description="CSV delimiter",
                required=False,
                default=","
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="parse_csv",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.PARSE_DATA,
                    description="Parse CSV data"
                )
            ]
        )

    async def execute(self, file_path: str, delimiter: str = ",") -> ToolResult:
        try:
            csv_path = Path(file_path).expanduser().resolve()

            if not csv_path.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {csv_path}")

            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f, delimiter=delimiter)
                data = list(reader)

            return ToolResult(
                success=True,
                output={
                    'file': str(csv_path),
                    'rows': len(data),
                    'columns': list(data[0].keys()) if data else [],
                    'data': data[:100]  # Limit to 100 rows
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ConvertFormatTool(Tool):
    """Convert between data formats"""

    def __init__(self):
        super().__init__()
        self.name = "convert_format"
        self.description = "Convert data between JSON, YAML, and CSV formats"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="input_file",
                type="string",
                description="Input file path",
                required=True
            ),
            ToolParameter(
                name="output_file",
                type="string",
                description="Output file path",
                required=True
            ),
            ToolParameter(
                name="output_format",
                type="string",
                description="Output format",
                required=True,
                enum=["json", "yaml", "csv"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="convert_format",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TRANSFORM_DATA,
                    description="Convert data formats"
                )
            ]
        )

    async def execute(self, input_file: str, output_file: str, output_format: str) -> ToolResult:
        try:
            import yaml

            # Read input file
            input_path = Path(input_file).expanduser().resolve()
            if not input_path.exists():
                return ToolResult(success=False, output=None, error=f"Input file not found: {input_path}")

            # Determine input format from extension
            if input_path.suffix == '.json':
                with open(input_path, 'r') as f:
                    data = json.load(f)
            elif input_path.suffix in ['.yaml', '.yml']:
                with open(input_path, 'r') as f:
                    data = yaml.safe_load(f)
            elif input_path.suffix == '.csv':
                with open(input_path, 'r') as f:
                    reader = csv.DictReader(f)
                    data = list(reader)
            else:
                return ToolResult(success=False, output=None, error=f"Unsupported input format: {input_path.suffix}")

            # Write output file
            output_path = Path(output_file).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)

            if output_format == 'json':
                with open(output_path, 'w') as f:
                    json.dump(data, f, indent=2)
            elif output_format == 'yaml':
                with open(output_path, 'w') as f:
                    yaml.dump(data, f, default_flow_style=False)
            elif output_format == 'csv':
                if not isinstance(data, list):
                    return ToolResult(success=False, output=None, error="CSV output requires list of dictionaries")

                with open(output_path, 'w', newline='') as f:
                    if data:
                        writer = csv.DictWriter(f, fieldnames=data[0].keys())
                        writer.writeheader()
                        writer.writerows(data)

            return ToolResult(
                success=True,
                output={
                    'input_file': str(input_path),
                    'output_file': str(output_path),
                    'output_format': output_format,
                    'converted': True
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class TransformDataTool(Tool):
    """Apply transformations to data"""

    def __init__(self):
        super().__init__()
        self.name = "transform_data"
        self.description = "Apply transformations to data (select fields, rename, etc.)"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="data",
                type="array",
                description="Input data (list of dicts)",
                required=True
            ),
            ToolParameter(
                name="select_fields",
                type="array",
                description="Fields to select (optional)",
                required=False
            ),
            ToolParameter(
                name="rename_fields",
                type="object",
                description="Field renaming map (old_name: new_name)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="transform_data",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TRANSFORM_DATA,
                    description="Transform data structure"
                )
            ]
        )

    async def execute(self, data: list, select_fields: list = None, rename_fields: dict = None) -> ToolResult:
        try:
            transformed = []

            for item in data:
                if not isinstance(item, dict):
                    continue

                new_item = {}

                # Select fields
                fields = select_fields if select_fields else item.keys()

                for field in fields:
                    if field in item:
                        # Rename if mapping exists
                        new_name = rename_fields.get(field, field) if rename_fields else field
                        new_item[new_name] = item[field]

                transformed.append(new_item)

            return ToolResult(
                success=True,
                output={
                    'input_count': len(data),
                    'output_count': len(transformed),
                    'transformed_data': transformed
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class AggregateDataTool(Tool):
    """Aggregate/summarize data"""

    def __init__(self):
        super().__init__()
        self.name = "aggregate_data"
        self.description = "Aggregate data by grouping and applying operations"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="data",
                type="array",
                description="Input data (list of dicts)",
                required=True
            ),
            ToolParameter(
                name="group_by",
                type="string",
                description="Field to group by",
                required=True
            ),
            ToolParameter(
                name="operation",
                type="string",
                description="Aggregation operation",
                required=False,
                default="count",
                enum=["count", "sum", "avg", "min", "max"]
            ),
            ToolParameter(
                name="value_field",
                type="string",
                description="Field to aggregate (for sum/avg/min/max)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="aggregate_data",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.AGGREGATE_DATA,
                    description="Aggregate data"
                )
            ]
        )

    async def execute(self, data: list, group_by: str, operation: str = "count", value_field: str = None) -> ToolResult:
        try:
            groups = {}

            for item in data:
                if not isinstance(item, dict) or group_by not in item:
                    continue

                key = item[group_by]
                if key not in groups:
                    groups[key] = []

                groups[key].append(item)

            # Apply aggregation
            results = {}
            for key, items in groups.items():
                if operation == "count":
                    results[key] = len(items)
                elif operation == "sum" and value_field:
                    results[key] = sum(float(item.get(value_field, 0)) for item in items)
                elif operation == "avg" and value_field:
                    values = [float(item.get(value_field, 0)) for item in items]
                    results[key] = sum(values) / len(values) if values else 0
                elif operation == "min" and value_field:
                    values = [float(item.get(value_field, 0)) for item in items]
                    results[key] = min(values) if values else 0
                elif operation == "max" and value_field:
                    values = [float(item.get(value_field, 0)) for item in items]
                    results[key] = max(values) if values else 0

            return ToolResult(
                success=True,
                output={
                    'group_by': group_by,
                    'operation': operation,
                    'groups': len(results),
                    'results': results
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class MergeDatasetsTool(Tool):
    """Merge multiple datasets"""

    def __init__(self):
        super().__init__()
        self.name = "merge_datasets"
        self.description = "Merge two datasets on a common key"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="dataset1",
                type="array",
                description="First dataset",
                required=True
            ),
            ToolParameter(
                name="dataset2",
                type="array",
                description="Second dataset",
                required=True
            ),
            ToolParameter(
                name="key_field",
                type="string",
                description="Field to join on",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="merge_datasets",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MERGE_DATA,
                    description="Merge datasets"
                )
            ]
        )

    async def execute(self, dataset1: list, dataset2: list, key_field: str) -> ToolResult:
        try:
            # Create lookup for dataset2
            lookup = {item[key_field]: item for item in dataset2 if isinstance(item, dict) and key_field in item}

            # Merge
            merged = []
            for item1 in dataset1:
                if not isinstance(item1, dict) or key_field not in item1:
                    continue

                key = item1[key_field]
                if key in lookup:
                    merged_item = {**item1, **lookup[key]}
                    merged.append(merged_item)

            return ToolResult(
                success=True,
                output={
                    'dataset1_count': len(dataset1),
                    'dataset2_count': len(dataset2),
                    'merged_count': len(merged),
                    'merged_data': merged
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class FilterDataTool(Tool):
    """Filter data by criteria"""

    def __init__(self):
        super().__init__()
        self.name = "filter_data"
        self.description = "Filter data based on field values"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="data",
                type="array",
                description="Input data",
                required=True
            ),
            ToolParameter(
                name="field",
                type="string",
                description="Field to filter on",
                required=True
            ),
            ToolParameter(
                name="operator",
                type="string",
                description="Comparison operator",
                required=False,
                default="eq",
                enum=["eq", "ne", "gt", "gte", "lt", "lte", "contains"]
            ),
            ToolParameter(
                name="value",
                type="string",
                description="Value to compare against",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="filter_data",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.FILTER_DATA,
                    description="Filter data by criteria"
                )
            ]
        )

    async def execute(self, data: list, field: str, operator: str = "eq", value: str = None) -> ToolResult:
        try:
            filtered = []

            for item in data:
                if not isinstance(item, dict) or field not in item:
                    continue

                item_value = item[field]

                match = False
                if operator == "eq":
                    match = str(item_value) == str(value)
                elif operator == "ne":
                    match = str(item_value) != str(value)
                elif operator == "gt":
                    match = float(item_value) > float(value)
                elif operator == "gte":
                    match = float(item_value) >= float(value)
                elif operator == "lt":
                    match = float(item_value) < float(value)
                elif operator == "lte":
                    match = float(item_value) <= float(value)
                elif operator == "contains":
                    match = str(value) in str(item_value)

                if match:
                    filtered.append(item)

            return ToolResult(
                success=True,
                output={
                    'input_count': len(data),
                    'filtered_count': len(filtered),
                    'filtered_data': filtered
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class SortDataTool(Tool):
    """Sort data"""

    def __init__(self):
        super().__init__()
        self.name = "sort_data"
        self.description = "Sort data by field"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="data",
                type="array",
                description="Input data",
                required=True
            ),
            ToolParameter(
                name="sort_by",
                type="string",
                description="Field to sort by",
                required=True
            ),
            ToolParameter(
                name="descending",
                type="boolean",
                description="Sort in descending order",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="sort_data",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.SORT_DATA,
                    description="Sort data"
                )
            ]
        )

    async def execute(self, data: list, sort_by: str, descending: bool = False) -> ToolResult:
        try:
            sorted_data = sorted(
                [item for item in data if isinstance(item, dict) and sort_by in item],
                key=lambda x: x[sort_by],
                reverse=descending
            )

            return ToolResult(
                success=True,
                output={
                    'count': len(sorted_data),
                    'sorted_by': sort_by,
                    'descending': descending,
                    'sorted_data': sorted_data
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class DeduplicateDataTool(Tool):
    """Remove duplicates from data"""

    def __init__(self):
        super().__init__()
        self.name = "deduplicate_data"
        self.description = "Remove duplicate entries from data"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="data",
                type="array",
                description="Input data",
                required=True
            ),
            ToolParameter(
                name="key_field",
                type="string",
                description="Field to use for deduplication (optional)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="deduplicate_data",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.FILTER_DATA,
                    description="Remove duplicate data"
                )
            ]
        )

    async def execute(self, data: list, key_field: str = None) -> ToolResult:
        try:
            seen = set()
            deduplicated = []

            for item in data:
                if not isinstance(item, dict):
                    continue

                # Use key field or entire item as identifier
                if key_field and key_field in item:
                    identifier = item[key_field]
                else:
                    identifier = json.dumps(item, sort_keys=True)

                if identifier not in seen:
                    seen.add(identifier)
                    deduplicated.append(item)

            return ToolResult(
                success=True,
                output={
                    'input_count': len(data),
                    'duplicates_removed': len(data) - len(deduplicated),
                    'output_count': len(deduplicated),
                    'deduplicated_data': deduplicated
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


# ===== ADVANCED DATA PROCESSING =====


class ParseJSONLTool(Tool):
    """
    Parse JSONL (JSON Lines) / Parquet / Arrow formats

    Features:
    - JSONL (newline-delimited JSON)
    - Parquet (columnar format, via pyarrow)
    - Arrow (in-memory columnar, via pyarrow)
    - Streaming support for large files
    - Schema preservation
    """

    def __init__(self):
        super().__init__()
        self.name = "parse_jsonl"
        self.description = "Parse JSONL, Parquet, or Arrow format data files"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to JSONL/Parquet/Arrow file",
                required=True
            ),
            ToolParameter(
                name="format",
                type="string",
                description="Data format",
                required=False,
                default="auto",
                enum=["auto", "jsonl", "parquet", "arrow"]
            ),
            ToolParameter(
                name="max_rows",
                type="number",
                description="Maximum rows to read (0 = all)",
                required=False,
                default=0,
                min_value=0
            ),
            ToolParameter(
                name="streaming",
                type="boolean",
                description="Use streaming mode for large files",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="parse_jsonl",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.PARSE_DATA,
                    description="Parse JSONL data"
                )
            ]
        )

    def _detect_format(self, file_path: Path) -> str:
        """Detect file format from extension"""
        suffix = file_path.suffix.lower()
        if suffix in ['.jsonl', '.ndjson']:
            return 'jsonl'
        elif suffix == '.parquet':
            return 'parquet'
        elif suffix == '.arrow':
            return 'arrow'
        return 'jsonl'  # Default

    def _read_jsonl(self, file_path: Path, max_rows: int) -> List[Dict]:
        """Read JSONL file"""
        data = []
        with open(file_path, 'r') as f:
            for i, line in enumerate(f):
                if max_rows > 0 and i >= max_rows:
                    break
                if line.strip():
                    data.append(json.loads(line))
        return data

    def _read_parquet(self, file_path: Path, max_rows: int) -> List[Dict]:
        """Read Parquet file"""
        try:
            import pyarrow.parquet as pq

            table = pq.read_table(file_path)
            if max_rows > 0:
                table = table.slice(0, max_rows)

            # Convert to list of dicts
            return table.to_pylist()

        except ImportError:
            raise ImportError("pyarrow not installed (install: pip install pyarrow)")

    def _read_arrow(self, file_path: Path, max_rows: int) -> List[Dict]:
        """Read Arrow file"""
        try:
            import pyarrow as pa

            with pa.OSFile(str(file_path), 'rb') as source:
                reader = pa.ipc.RecordBatchFileReader(source)
                table = reader.read_all()

                if max_rows > 0:
                    table = table.slice(0, max_rows)

                return table.to_pylist()

        except ImportError:
            raise ImportError("pyarrow not installed (install: pip install pyarrow)")

    async def execute(
        self,
        file_path: str,
        format: str = "auto",
        max_rows: int = 0,
        streaming: bool = False
    ) -> ToolResult:
        """Parse structured data file"""
        try:
            path = Path(file_path)

            if not path.exists():
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"File not found: {file_path}"
                )

            # Detect format
            if format == "auto":
                format = self._detect_format(path)

            # Read data
            if format == "jsonl":
                data = self._read_jsonl(path, max_rows)
            elif format == "parquet":
                data = self._read_parquet(path, max_rows)
            elif format == "arrow":
                data = self._read_arrow(path, max_rows)
            else:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Unsupported format: {format}"
                )

            return ToolResult(
                success=True,
                output={
                    'format': format,
                    'rows_read': len(data),
                    'file_path': str(path),
                    'data': data
                }
            )

        except Exception as e:
            logger.error(f"Failed to parse {format} file: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class SchemaInferenceTool(Tool):
    """
    Infer and validate data schemas

    Features:
    - Automatic schema inference from data
    - JSON Schema validation
    - Type detection and coercion
    - Required/optional field detection
    - Value constraints (min/max, enum)
    """

    def __init__(self):
        super().__init__()
        self.name = "schema_inference"
        self.description = "Infer schema from data (provide file_path OR data)"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to CSV/JSON/JSONL file (alternative to data parameter)",
                required=False
            ),
            ToolParameter(
                name="data",
                type="array",
                description="List of data records to analyze (alternative to file_path)",
                required=False
            ),
            ToolParameter(
                name="validate_against",
                type="object",
                description="JSON Schema to validate against (optional)",
                required=False
            ),
            ToolParameter(
                name="infer_constraints",
                type="boolean",
                description="Infer value constraints (min/max, enum)",
                required=False,
                default=True
            ),
            ToolParameter(
                name="sample_size",
                type="number",
                description="Number of records to sample for inference (0 = all)",
                required=False,
                default=1000
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="schema_inference",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Infer data schemas"
                )
            ]
        )

    def _infer_type(self, value: Any) -> str:
        """Infer JSON Schema type from Python value"""
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return "boolean"
        elif isinstance(value, int):
            return "integer"
        elif isinstance(value, float):
            return "number"
        elif isinstance(value, str):
            return "string"
        elif isinstance(value, list):
            return "array"
        elif isinstance(value, dict):
            return "object"
        return "string"  # Default

    def _infer_schema(self, data: List[Dict], infer_constraints: bool, sample_size: int) -> Dict[str, Any]:
        """Infer JSON Schema from data"""
        if not data:
            return {"type": "array", "items": {}}

        # Sample data
        sample = data[:sample_size] if sample_size > 0 else data

        # Collect field information
        field_info = defaultdict(lambda: {
            "types": set(),
            "required_count": 0,
            "values": [],
            "nulls": 0
        })

        for record in sample:
            if not isinstance(record, dict):
                continue

            # Track which fields are present
            for key in record:
                value = record[key]
                field_info[key]["required_count"] += 1
                field_info[key]["types"].add(self._infer_type(value))

                if value is None:
                    field_info[key]["nulls"] += 1
                elif infer_constraints:
                    field_info[key]["values"].append(value)

        # Build schema
        properties = {}
        required = []

        for field, info in field_info.items():
            # Determine type (most common)
            types = list(info["types"] - {"null"})
            if not types:
                types = ["null"]

            field_schema = {}

            if len(types) == 1:
                field_schema["type"] = types[0]
            else:
                field_schema["type"] = types  # Multiple types

            # Handle nullable fields
            if info["nulls"] > 0:
                if isinstance(field_schema["type"], list):
                    if "null" not in field_schema["type"]:
                        field_schema["type"].append("null")
                else:
                    field_schema["type"] = [field_schema["type"], "null"]

            # Infer constraints
            if infer_constraints and info["values"]:
                values = info["values"]

                # For numbers, infer min/max
                if types[0] in ["integer", "number"]:
                    try:
                        numeric_values = [v for v in values if v is not None]
                        if numeric_values:
                            field_schema["minimum"] = min(numeric_values)
                            field_schema["maximum"] = max(numeric_values)
                    except (TypeError, ValueError):
                        pass

                # For strings, infer enum if low cardinality
                elif types[0] == "string":
                    unique_values = set(v for v in values if v is not None)
                    if len(unique_values) <= 10 and len(values) > 10:
                        field_schema["enum"] = sorted(unique_values)

            properties[field] = field_schema

            # Mark as required if present in >90% of records
            if info["required_count"] / len(sample) > 0.9:
                required.append(field)

        schema = {
            "type": "object",
            "properties": properties,
            "required": required if required else []
        }

        return schema

    def _validate_schema(self, data: List[Dict], schema: Dict) -> Tuple[bool, List[str]]:
        """Validate data against JSON Schema"""
        errors = []

        for i, record in enumerate(data):
            # Check required fields
            for field in schema.get("required", []):
                if field not in record:
                    errors.append(f"Record {i}: Missing required field '{field}'")

            # Check field types
            for field, value in record.items():
                if field not in schema.get("properties", {}):
                    continue

                field_schema = schema["properties"][field]
                expected_type = field_schema.get("type")

                if expected_type:
                    actual_type = self._infer_type(value)

                    if isinstance(expected_type, list):
                        if actual_type not in expected_type:
                            errors.append(f"Record {i}: Field '{field}' has type '{actual_type}', expected one of {expected_type}")
                    elif actual_type != expected_type:
                        errors.append(f"Record {i}: Field '{field}' has type '{actual_type}', expected '{expected_type}'")

                # Check constraints
                if "minimum" in field_schema and value is not None:
                    if value < field_schema["minimum"]:
                        errors.append(f"Record {i}: Field '{field}' value {value} below minimum {field_schema['minimum']}")

                if "maximum" in field_schema and value is not None:
                    if value > field_schema["maximum"]:
                        errors.append(f"Record {i}: Field '{field}' value {value} above maximum {field_schema['maximum']}")

                if "enum" in field_schema and value is not None:
                    if value not in field_schema["enum"]:
                        errors.append(f"Record {i}: Field '{field}' value '{value}' not in enum {field_schema['enum']}")

        return len(errors) == 0, errors

    async def execute(
        self,
        file_path: Optional[str] = None,
        data: Optional[List[Dict]] = None,
        validate_against: Optional[Dict] = None,
        infer_constraints: bool = True,
        sample_size: int = 1000
    ) -> ToolResult:
        """Infer schema from data"""
        try:
            # Load data from file if file_path provided
            if file_path:
                file_path_obj = Path(file_path).expanduser().resolve()
                if file_path.endswith('.csv'):
                    import csv
                    data = []
                    with open(file_path_obj, 'r') as f:
                        reader = csv.DictReader(f)
                        data = list(reader)
                elif file_path.endswith('.jsonl'):
                    data = []
                    with open(file_path_obj, 'r') as f:
                        for line in f:
                            data.append(json.loads(line.strip()))
                elif file_path.endswith('.json'):
                    with open(file_path_obj, 'r') as f:
                        loaded = json.load(f)
                        data = loaded if isinstance(loaded, list) else [loaded]
                else:
                    return ToolResult(success=False, output=None, error=f"Unsupported file format: {file_path}")

            if not data:
                return ToolResult(success=False, output=None, error="Either file_path or data must be provided")

            # Infer schema from data
            inferred_schema = self._infer_schema(data, infer_constraints, sample_size)

            result = {
                'record_count': len(data),
                'inferred_schema': inferred_schema,
                'fields_detected': len(inferred_schema.get("properties", {})),
                'required_fields': inferred_schema.get("required", [])
            }

            # Validate if schema provided
            if validate_against:
                valid, errors = self._validate_schema(data, validate_against)
                result['validation'] = {
                    'valid': valid,
                    'errors': errors[:100],  # Limit to first 100 errors
                    'error_count': len(errors)
                }

            return ToolResult(success=True, output=result)

        except Exception as e:
            logger.error(f"Schema inference failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class PIIScrubbingTool(Tool):
    """
    Scrub/redact PII (Personally Identifiable Information) from data

    Features:
    - Email addresses
    - Phone numbers
    - SSN, credit card numbers
    - IP addresses
    - Names (basic patterns)
    - Custom patterns
    - Configurable redaction strategies (mask, hash, remove)
    """

    def __init__(self):
        super().__init__()
        self.name = "pii_scrubbing"
        self.description = "Detect and redact PII from data (provide file_path OR data)"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to CSV/JSON/JSONL file (alternative to data parameter)",
                required=False
            ),
            ToolParameter(
                name="data",
                type="object",
                description="Data to scrub (dict, list, or string) (alternative to file_path)",
                required=False
            ),
            ToolParameter(
                name="pii_types",
                type="array",
                description="PII types to detect: email, phone, ssn, credit_card, ip, name",
                required=False
            ),
            ToolParameter(
                name="redaction_strategy",
                type="string",
                description="How to redact PII",
                required=False,
                default="mask",
                enum=["mask", "hash", "remove", "tag"]
            ),
            ToolParameter(
                name="custom_patterns",
                type="object",
                description="Custom regex patterns for PII detection",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="pii_scrubbing",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.FILTER_DATA,
                    description="Scrub PII from data"
                )
            ]
        )

        # PII detection patterns
        self.pii_patterns = {
            "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            "phone": r'\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b',
            "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
            "credit_card": r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
            "ip": r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
            "name": r'\b(?:[A-Z][a-z]+ ){1,2}[A-Z][a-z]+\b'  # Simple pattern
        }

    def _redact_value(self, value: str, pii_type: str, strategy: str) -> str:
        """Redact a PII value based on strategy"""
        if strategy == "mask":
            # Show first/last few chars
            if len(value) <= 4:
                return "***"
            return value[:2] + "*" * (len(value) - 4) + value[-2:]

        elif strategy == "hash":
            # SHA256 hash
            return hashlib.sha256(value.encode()).hexdigest()[:16]

        elif strategy == "remove":
            return ""

        elif strategy == "tag":
            return f"[REDACTED_{pii_type.upper()}]"

        return value

    def _scrub_string(
        self,
        text: str,
        pii_types: List[str],
        strategy: str,
        custom_patterns: Dict[str, str]
    ) -> Tuple[str, List[Dict]]:
        """Scrub PII from a string"""
        detections = []
        scrubbed = text

        # Combine built-in and custom patterns
        patterns = {**self.pii_patterns}
        if custom_patterns:
            patterns.update(custom_patterns)

        # Only use requested PII types
        if pii_types:
            patterns = {k: v for k, v in patterns.items() if k in pii_types}

        # Detect and redact each pattern
        for pii_type, pattern in patterns.items():
            matches = list(re.finditer(pattern, text))

            for match in matches:
                original = match.group(0)
                redacted = self._redact_value(original, pii_type, strategy)
                scrubbed = scrubbed.replace(original, redacted)

                detections.append({
                    'type': pii_type,
                    'original': original,
                    'redacted': redacted,
                    'position': match.start()
                })

        return scrubbed, detections

    def _scrub_recursive(
        self,
        data: Any,
        pii_types: List[str],
        strategy: str,
        custom_patterns: Dict[str, str]
    ) -> Tuple[Any, List[Dict]]:
        """Recursively scrub PII from nested data structures"""
        all_detections = []

        if isinstance(data, str):
            scrubbed, detections = self._scrub_string(data, pii_types, strategy, custom_patterns)
            all_detections.extend(detections)
            return scrubbed, all_detections

        elif isinstance(data, dict):
            scrubbed = {}
            for key, value in data.items():
                scrubbed_value, detections = self._scrub_recursive(value, pii_types, strategy, custom_patterns)
                scrubbed[key] = scrubbed_value
                all_detections.extend(detections)
            return scrubbed, all_detections

        elif isinstance(data, list):
            scrubbed = []
            for item in data:
                scrubbed_item, detections = self._scrub_recursive(item, pii_types, strategy, custom_patterns)
                scrubbed.append(scrubbed_item)
                all_detections.extend(detections)
            return scrubbed, all_detections

        else:
            return data, []

    async def execute(
        self,
        file_path: Optional[str] = None,
        data: Optional[Any] = None,
        pii_types: Optional[List[str]] = None,
        redaction_strategy: str = "mask",
        custom_patterns: Optional[Dict[str, str]] = None
    ) -> ToolResult:
        """Scrub PII from data"""
        try:
            # Load data from file if file_path provided
            if file_path:
                file_path_obj = Path(file_path).expanduser().resolve()
                if file_path.endswith('.csv'):
                    import csv
                    data = []
                    with open(file_path_obj, 'r') as f:
                        reader = csv.DictReader(f)
                        data = list(reader)
                elif file_path.endswith('.jsonl'):
                    data = []
                    with open(file_path_obj, 'r') as f:
                        for line in f:
                            data.append(json.loads(line.strip()))
                elif file_path.endswith('.json'):
                    with open(file_path_obj, 'r') as f:
                        data = json.load(f)
                else:
                    return ToolResult(success=False, output=None, error=f"Unsupported file format: {file_path}")

            if data is None:
                return ToolResult(success=False, output=None, error="Either file_path or data must be provided")

            # Default to all PII types
            if not pii_types:
                pii_types = list(self.pii_patterns.keys())

            # Scrub data
            scrubbed_data, detections = self._scrub_recursive(
                data,
                pii_types,
                redaction_strategy,
                custom_patterns or {}
            )

            # Group detections by type
            by_type = defaultdict(int)
            for detection in detections:
                by_type[detection['type']] += 1

            return ToolResult(
                success=True,
                output={
                    'scrubbed_data': scrubbed_data,
                    'pii_detected': len(detections),
                    'detections_by_type': dict(by_type),
                    'redaction_strategy': redaction_strategy,
                    'sample_detections': detections[:10]  # First 10 for review
                }
            )

        except Exception as e:
            logger.error(f"PII scrubbing failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class DatasetProfilingTool(Tool):
    """
    Profile datasets for quality analysis

    Features:
    - Missing value analysis
    - Data type distribution
    - Statistical summaries (mean, median, std)
    - Outlier detection
    - Data drift detection (compare two datasets)
    - Cardinality analysis
    """

    def __init__(self):
        super().__init__()
        self.name = "dataset_profiling"
        self.description = "Analyze dataset quality (provide file_path OR data)"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to CSV/JSON/JSONL file (alternative to data parameter)",
                required=False
            ),
            ToolParameter(
                name="data",
                type="array",
                description="Dataset to profile (list of dicts) (alternative to file_path)",
                required=False
            ),
            ToolParameter(
                name="compare_with",
                type="array",
                description="Reference dataset for drift detection",
                required=False
            ),
            ToolParameter(
                name="outlier_threshold",
                type="number",
                description="Z-score threshold for outlier detection",
                required=False,
                default=3.0
            ),
            ToolParameter(
                name="include_statistics",
                type="boolean",
                description="Include statistical summaries",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="dataset_profiling",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Profile datasets"
                )
            ]
        )

    def _analyze_missingness(self, data: List[Dict]) -> Dict[str, Any]:
        """Analyze missing values"""
        if not data:
            return {}

        # Count nulls per field
        field_nulls = defaultdict(int)
        field_total = defaultdict(int)

        for record in data:
            if not isinstance(record, dict):
                continue

            for key in record:
                field_total[key] += 1
                if record[key] is None or record[key] == "":
                    field_nulls[key] += 1

        # Calculate missingness rate
        missingness = {}
        for field in field_total:
            null_count = field_nulls[field]
            total_count = field_total[field]
            missingness[field] = {
                'null_count': null_count,
                'total_count': total_count,
                'null_rate': null_count / total_count if total_count > 0 else 0
            }

        return missingness

    def _compute_statistics(self, values: List) -> Dict[str, Any]:
        """Compute statistical summary for numeric data"""
        import statistics

        # Filter numeric values
        numeric = [v for v in values if v is not None and isinstance(v, (int, float))]

        if not numeric:
            return {}

        stats = {
            'count': len(numeric),
            'mean': statistics.mean(numeric),
            'median': statistics.median(numeric),
            'std': statistics.stdev(numeric) if len(numeric) > 1 else 0,
            'min': min(numeric),
            'max': max(numeric),
            'q25': statistics.quantiles(numeric, n=4)[0] if len(numeric) >= 4 else None,
            'q75': statistics.quantiles(numeric, n=4)[2] if len(numeric) >= 4 else None
        }

        return stats

    def _detect_outliers(self, values: List, threshold: float) -> List[int]:
        """Detect outliers using z-score"""
        import statistics

        numeric = [(i, v) for i, v in enumerate(values) if v is not None and isinstance(v, (int, float))]

        if len(numeric) < 2:
            return []

        values_only = [v for _, v in numeric]
        mean = statistics.mean(values_only)
        std = statistics.stdev(values_only)

        if std == 0:
            return []

        outliers = []
        for idx, value in numeric:
            z_score = abs((value - mean) / std)
            if z_score > threshold:
                outliers.append(idx)

        return outliers

    def _analyze_drift(self, data1: List[Dict], data2: List[Dict]) -> Dict[str, Any]:
        """Detect data drift between two datasets"""
        drift = {}

        # Get all fields
        all_fields = set()
        for record in data1 + data2:
            if isinstance(record, dict):
                all_fields.update(record.keys())

        for field in all_fields:
            # Collect values from both datasets
            values1 = [r[field] for r in data1 if isinstance(r, dict) and field in r]
            values2 = [r[field] for r in data2 if isinstance(r, dict) and field in r]

            if not values1 or not values2:
                continue

            # Compare distributions
            drift_detected = False
            drift_metrics = {}

            # For numeric fields, compare means
            numeric1 = [v for v in values1 if isinstance(v, (int, float))]
            numeric2 = [v for v in values2 if isinstance(v, (int, float))]

            if numeric1 and numeric2:
                import statistics
                mean1 = statistics.mean(numeric1)
                mean2 = statistics.mean(numeric2)

                # Simple drift: >20% change in mean
                if mean1 != 0:
                    drift_pct = abs((mean2 - mean1) / mean1)
                    if drift_pct > 0.2:
                        drift_detected = True
                    drift_metrics['mean_drift'] = drift_pct

            # For categorical, compare distributions
            else:
                dist1 = {}
                dist2 = {}
                for v in values1:
                    dist1[v] = dist1.get(v, 0) + 1
                for v in values2:
                    dist2[v] = dist2.get(v, 0) + 1

                # Check if new categories appeared
                new_categories = set(dist2.keys()) - set(dist1.keys())
                if new_categories:
                    drift_detected = True
                    drift_metrics['new_categories'] = list(new_categories)

            drift[field] = {
                'drift_detected': drift_detected,
                'metrics': drift_metrics
            }

        return drift

    async def execute(
        self,
        file_path: Optional[str] = None,
        data: Optional[List[Dict]] = None,
        compare_with: Optional[List[Dict]] = None,
        outlier_threshold: float = 3.0,
        include_statistics: bool = True
    ) -> ToolResult:
        """Profile dataset quality"""
        try:
            # Load data from file if file_path provided
            if file_path:
                file_path_obj = Path(file_path).expanduser().resolve()
                if file_path.endswith('.csv'):
                    import csv
                    data = []
                    with open(file_path_obj, 'r') as f:
                        reader = csv.DictReader(f)
                        data = list(reader)
                elif file_path.endswith('.jsonl'):
                    data = []
                    with open(file_path_obj, 'r') as f:
                        for line in f:
                            data.append(json.loads(line.strip()))
                elif file_path.endswith('.json'):
                    with open(file_path_obj, 'r') as f:
                        loaded = json.load(f)
                        data = loaded if isinstance(loaded, list) else [loaded]
                else:
                    return ToolResult(success=False, output=None, error=f"Unsupported file format: {file_path}")

            if not data:
                return ToolResult(success=False, output=None, error="Either file_path or data must be provided")

            profile = {
                'record_count': len(data),
                'fields': {}
            }

            # Analyze missingness
            missingness = self._analyze_missingness(data)
            profile['missingness'] = missingness

            # Analyze each field
            if data and isinstance(data[0], dict):
                all_fields = set()
                for record in data:
                    if isinstance(record, dict):
                        all_fields.update(record.keys())

                for field in all_fields:
                    values = [r[field] for r in data if isinstance(r, dict) and field in r]

                    field_profile = {
                        'value_count': len(values),
                        'unique_count': len(set(values)),
                        'cardinality': len(set(values)) / len(values) if values else 0
                    }

                    # Statistics for numeric fields
                    if include_statistics:
                        stats = self._compute_statistics(values)
                        if stats:
                            field_profile['statistics'] = stats

                    # Outlier detection
                    outliers = self._detect_outliers(values, outlier_threshold)
                    if outliers:
                        field_profile['outliers'] = {
                            'count': len(outliers),
                            'indices': outliers[:100]  # Limit to first 100
                        }

                    profile['fields'][field] = field_profile

            # Drift detection
            if compare_with:
                drift = self._analyze_drift(data, compare_with)
                profile['drift'] = drift

                # Summary
                drift_fields = [f for f, d in drift.items() if d['drift_detected']]
                profile['drift_summary'] = {
                    'total_fields': len(drift),
                    'drifted_fields': len(drift_fields),
                    'drift_rate': len(drift_fields) / len(drift) if drift else 0
                }

            return ToolResult(success=True, output=profile)

        except Exception as e:
            logger.error(f"Dataset profiling failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))
