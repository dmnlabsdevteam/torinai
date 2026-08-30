#!/usr/bin/env python3
"""
Search and Analysis Tools
=========================
Tools for searching and analyzing code.

Available Tools:
- semantic_search: Semantic code search using embeddings
- grep_search: Fast text/regex search
- analyze_code: Static code analysis

Author: Torin AI Team
"""

import logging
import re
import subprocess
import ast
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from collections import defaultdict, deque

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata


logger = logging.getLogger(__name__)


class SemanticSearchTool(Tool):
    """Search code semantically using embeddings"""
    
    def __init__(self):
        super().__init__()
        self.name = "semantic_search"
        self.description = "Search codebase semantically using natural language query"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="query",
                type="string",
                description="Natural language search query",
                required=True
            ),
            ToolParameter(
                name="workspace_path",
                type="string",
                description="Path to workspace to search",
                required=False,
                default="."
            ),
            ToolParameter(
                name="max_results",
                type="number",
                description="Maximum number of results",
                required=False,
                default=10,
                min_value=1,
                max_value=100
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="semantic_search",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.SEMANTIC_SEARCH,
                    description="Search code semantically using natural language"
                )
            ]
        )

    async def execute(
        self,
        query: str,
        workspace_path: str = ".",
        max_results: int = 10
    ) -> ToolResult:
        """Perform semantic search"""
        try:
            # Use embedding service directly
            from core.memory.utils.embedding_service import get_embedding_service

            embedding_service = get_embedding_service()
            if not embedding_service or not embedding_service.initialized:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Embedding service not available"
                )

            # Get workspace files
            workspace = Path(workspace_path).resolve()
            python_files = list(workspace.glob("**/*.py"))[:200]  # Limit search scope

            # Create embeddings for search
            file_contents = []
            file_paths = []

            for file in python_files:
                try:
                    content = file.read_text(encoding='utf-8')
                    file_contents.append(content[:2000])  # First 2000 chars
                    file_paths.append(str(file.relative_to(workspace)))
                except:
                    continue

            if not file_contents:
                return ToolResult(
                    success=True,
                    output={"matches": [], "count": 0}
                )

            # Get query embedding
            query_embedding = embedding_service.generate_embedding(query)

            # Get file embeddings
            file_embeddings = embedding_service.batch_embed(file_contents)

            # Calculate similarities using numpy dot product
            import numpy as np
            similarities = []
            query_norm = np.array(query_embedding)
            query_norm = query_norm / np.linalg.norm(query_norm)

            for i, file_emb in enumerate(file_embeddings):
                file_norm = np.array(file_emb)
                file_norm = file_norm / np.linalg.norm(file_norm)
                similarity = float(np.dot(query_norm, file_norm))
                similarities.append((file_paths[i], similarity, file_contents[i]))
            
            # Sort by similarity
            similarities.sort(key=lambda x: x[1], reverse=True)
            top_matches = similarities[:max_results]
            
            return ToolResult(
                success=True,
                output={
                    "query": query,
                    "matches": [
                        {
                            "file": match[0],
                            "similarity": float(match[1]),
                            "preview": match[2][:200] + "..."
                        }
                        for match in top_matches
                    ],
                    "count": len(top_matches)
                }
            )
            
        except Exception as e:
            logger.error(f"Error in semantic search: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class GrepSearchTool(Tool):
    """Fast text/regex search using grep"""
    
    def __init__(self):
        super().__init__()
        self.name = "grep_search"
        self.description = "Search for text patterns in files using grep (supports regex)"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="pattern",
                type="string",
                description="Search pattern (text or regex)",
                required=True
            ),
            ToolParameter(
                name="path",
                type="string",
                description="Path to search in",
                required=False,
                default="."
            ),
            ToolParameter(
                name="is_regex",
                type="boolean",
                description="Whether pattern is a regex",
                required=False,
                default=False
            ),
            ToolParameter(
                name="file_pattern",
                type="string",
                description="File pattern to search (e.g., '*.py')",
                required=False
            ),
            ToolParameter(
                name="max_results",
                type="number",
                description="Maximum number of results",
                required=False,
                default=100,
                min_value=1,
                max_value=1000
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="grep_search",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.TEXT_SEARCH,
                    description="Fast text/regex search across codebase"
                )
            ]
        )

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        is_regex: bool = False,
        file_pattern: Optional[str] = None,
        max_results: int = 100
    ) -> ToolResult:
        """Perform grep search"""
        try:
            search_path = Path(path).resolve()
            
            if not search_path.exists():
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Path not found: {search_path}"
                )
            
            # Build grep command
            cmd = ["grep", "-r", "-n"]  # Recursive, with line numbers
            
            if not is_regex:
                cmd.append("-F")  # Fixed string search
            
            if file_pattern:
                cmd.extend(["--include", file_pattern])
            
            cmd.extend([pattern, str(search_path)])
            
            # Execute grep
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Parse results
            matches = []
            for line in result.stdout.splitlines()[:max_results]:
                if ':' in line:
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        matches.append({
                            "file": parts[0],
                            "line": int(parts[1]) if parts[1].isdigit() else 0,
                            "content": parts[2].strip()
                        })
            
            return ToolResult(
                success=True,
                output={
                    "pattern": pattern,
                    "matches": matches,
                    "count": len(matches),
                    "truncated": len(result.stdout.splitlines()) > max_results
                }
            )
            
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output=None,
                error="Search timed out after 30 seconds"
            )
        except Exception as e:
            logger.error(f"Error in grep search: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class AnalyzeCodeTool(Tool):
    """Analyze code for patterns, imports, functions, etc."""
    
    def __init__(self):
        super().__init__()
        self.name = "analyze_code"
        self.description = "Analyze Python code structure (imports, functions, classes, etc.)"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Path to Python file to analyze",
                required=True
            ),
            ToolParameter(
                name="analysis_type",
                type="string",
                description="Type of analysis to perform",
                required=False,
                default="all",
                enum=["all", "imports", "functions", "classes", "complexity"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_code",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze Python code structure, imports, functions, and classes"
                )
            ]
        )

    async def execute(
        self,
        file_path: str,
        analysis_type: str = "all"
    ) -> ToolResult:
        """Analyze code"""
        try:
            import ast
            
            path = Path(file_path).resolve()
            
            if not path.exists():
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"File not found: {path}"
                )
            
            # Read and parse file
            code = path.read_text(encoding='utf-8')
            tree = ast.parse(code)
            
            # Analyze
            analysis = {}
            
            if analysis_type in ["all", "imports"]:
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        for alias in node.names:
                            imports.append(f"{module}.{alias.name}")
                analysis["imports"] = sorted(set(imports))
            
            if analysis_type in ["all", "functions"]:
                functions = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        functions.append({
                            "name": node.name,
                            "line": node.lineno,
                            "args": len(node.args.args),
                            "is_async": isinstance(node, ast.AsyncFunctionDef)
                        })
                analysis["functions"] = functions
            
            if analysis_type in ["all", "classes"]:
                classes = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        methods = [
                            n.name for n in node.body
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        ]
                        classes.append({
                            "name": node.name,
                            "line": node.lineno,
                            "methods": methods,
                            "bases": [b.id if isinstance(b, ast.Name) else str(b) for b in node.bases]
                        })
                analysis["classes"] = classes
            
            if analysis_type in ["all", "complexity"]:
                analysis["complexity"] = {
                    "total_lines": len(code.splitlines()),
                    "code_lines": len([l for l in code.splitlines() if l.strip() and not l.strip().startswith('#')]),
                    "total_functions": len([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]),
                    "total_classes": len([n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)])
                }
            
            return ToolResult(
                success=True,
                output={
                    "file": str(path),
                    "analysis": analysis
                }
            )
            
        except SyntaxError as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Syntax error in file: {e}"
            )
        except Exception as e:
            logger.error(f"Error analyzing code: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )
class AnalyzeCodeQualityTool(Tool):
    """Analyze code quality metrics"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_code_quality"
        self.description = "Analyze Python code quality (complexity, maintainability)"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Python file to analyze",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_code_quality",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze code quality metrics"
                ),
                CapabilityMetadata(
                    capability=Capability.ASSESS_QUALITY,
                    description="Assess code maintainability and complexity"
                )
            ]
        )

    async def execute(self, file_path: str) -> ToolResult:
        try:
            file = Path(file_path).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {file}")

            with open(file, 'r') as f:
                code = f.read()

            # Parse AST
            tree = ast.parse(code)

            # Count metrics
            functions = []
            classes = []
            imports = []
            total_lines = len(code.splitlines())
            blank_lines = len([l for l in code.splitlines() if not l.strip()])
            comment_lines = len([l for l in code.splitlines() if l.strip().startswith('#')])

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Calculate cyclomatic complexity (simplified)
                    complexity = 1
                    for subnode in ast.walk(node):
                        if isinstance(subnode, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                            complexity += 1
                        elif isinstance(subnode, ast.BoolOp):
                            complexity += len(subnode.values) - 1

                    functions.append({
                        'name': node.name,
                        'line': node.lineno,
                        'complexity': complexity,
                        'lines': len(ast.unparse(node).splitlines()) if hasattr(ast, 'unparse') else 0
                    })
                elif isinstance(node, ast.ClassDef):
                    classes.append({
                        'name': node.name,
                        'line': node.lineno,
                        'methods': len([n for n in node.body if isinstance(n, ast.FunctionDef)])
                    })
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports.append(ast.unparse(node) if hasattr(ast, 'unparse') else str(node))

            # Calculate maintainability metrics
            code_lines = total_lines - blank_lines - comment_lines
            comment_ratio = comment_lines / total_lines if total_lines > 0 else 0
            avg_complexity = sum(f['complexity'] for f in functions) / len(functions) if functions else 0

            return ToolResult(
                success=True,
                output={
                    'file': str(file),
                    'metrics': {
                        'total_lines': total_lines,
                        'code_lines': code_lines,
                        'blank_lines': blank_lines,
                        'comment_lines': comment_lines,
                        'comment_ratio': round(comment_ratio, 2),
                        'num_functions': len(functions),
                        'num_classes': len(classes),
                        'num_imports': len(imports),
                        'avg_complexity': round(avg_complexity, 2)
                    },
                    'functions': functions[:10],  # Top 10 by complexity
                    'classes': classes,
                    'high_complexity_functions': [f for f in functions if f['complexity'] > 10]
                }
            )

        except SyntaxError as e:
            return ToolResult(success=False, output=None, error=f"Syntax error in file: {e}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class AnalyzeDependenciesTool(Tool):
    """Analyze project dependencies"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_dependencies"
        self.description = "Analyze Python project dependencies from requirements.txt or imports"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="project_path",
                type="string",
                description="Project directory path",
                required=True
            ),
            ToolParameter(
                name="analyze_type",
                type="string",
                description="Analysis type",
                required=False,
                default="requirements",
                enum=["requirements", "imports", "both"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_dependencies",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_DEPENDENCIES,
                    description="Analyze project dependencies from requirements.txt or imports"
                )
            ]
        )

    async def execute(self, project_path: str, analyze_type: str = "requirements") -> ToolResult:
        try:
            project = Path(project_path).expanduser().resolve()
            if not project.exists():
                return ToolResult(success=False, output=None, error=f"Project path not found: {project}")

            result = {
                'project_path': str(project),
                'requirements': [],
                'imports': {},
                'unused_requirements': [],
                'missing_requirements': []
            }

            # Parse requirements.txt if exists
            requirements_file = project / 'requirements.txt'
            if requirements_file.exists() and analyze_type in ['requirements', 'both']:
                with open(requirements_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # Parse requirement (handle ==, >=, etc.)
                            package = re.split(r'[=><]', line)[0].strip()
                            result['requirements'].append(line)

            # Analyze imports from Python files
            if analyze_type in ['imports', 'both']:
                imports_count = defaultdict(int)
                for py_file in project.rglob('*.py'):
                    try:
                        with open(py_file, 'r') as f:
                            tree = ast.parse(f.read())
                            for node in ast.walk(tree):
                                if isinstance(node, ast.Import):
                                    for alias in node.names:
                                        imports_count[alias.name.split('.')[0]] += 1
                                elif isinstance(node, ast.ImportFrom):
                                    if node.module:
                                        imports_count[node.module.split('.')[0]] += 1
                    except:
                        continue

                result['imports'] = dict(sorted(imports_count.items(), key=lambda x: x[1], reverse=True))

            # Find potential issues if both analyzed
            if analyze_type == 'both' and result['requirements']:
                requirement_packages = {re.split(r'[=><]', r)[0].strip().lower() for r in result['requirements']}
                imported_packages = {pkg.lower() for pkg in result['imports'].keys()}

                # Filter out standard library
                stdlib = {'os', 'sys', 'json', 're', 'datetime', 'time', 'logging', 'pathlib', 'typing', 'collections', 'asyncio'}
                imported_packages = imported_packages - stdlib

                result['unused_requirements'] = list(requirement_packages - imported_packages)
                result['missing_requirements'] = list(imported_packages - requirement_packages)

            return ToolResult(success=True, output=result)

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class FindDeadCodeTool(Tool):
    """Find unused functions and imports"""

    def __init__(self):
        super().__init__()
        self.name = "find_dead_code"
        self.description = "Find potentially unused functions and imports in Python code"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Directory to analyze",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="find_dead_code",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_ISSUE,
                    description="Detect unused code and dead functions"
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze code usage patterns"
                )
            ]
        )

    async def execute(self, directory_path: str) -> ToolResult:
        try:
            directory = Path(directory_path).expanduser().resolve()
            if not directory.exists():
                return ToolResult(success=False, output=None, error=f"Directory not found: {directory}")

            defined_functions = {}  # {name: (file, line)}
            function_calls = set()
            defined_imports = {}  # {name: (file, line)}
            import_usage = set()

            # First pass: collect all definitions
            for py_file in directory.rglob('*.py'):
                try:
                    with open(py_file, 'r') as f:
                        tree = ast.parse(f.read())

                    for node in ast.walk(tree):
                        # Track function definitions
                        if isinstance(node, ast.FunctionDef):
                            func_name = node.name
                            if not func_name.startswith('_'):  # Skip private functions
                                defined_functions[func_name] = (str(py_file), node.lineno)

                        # Track imports
                        elif isinstance(node, ast.Import):
                            for alias in node.names:
                                name = alias.asname if alias.asname else alias.name
                                defined_imports[name] = (str(py_file), node.lineno)
                        elif isinstance(node, ast.ImportFrom):
                            for alias in node.names:
                                name = alias.asname if alias.asname else alias.name
                                defined_imports[name] = (str(py_file), node.lineno)

                        # Track function calls
                        elif isinstance(node, ast.Call):
                            if isinstance(node.func, ast.Name):
                                function_calls.add(node.func.id)

                        # Track name usage (for imports)
                        elif isinstance(node, ast.Name):
                            import_usage.add(node.id)

                except:
                    continue

            # Find unused
            unused_functions = []
            for func_name, (file, line) in defined_functions.items():
                if func_name not in function_calls:
                    unused_functions.append({
                        'name': func_name,
                        'file': file,
                        'line': line
                    })

            unused_imports = []
            for import_name, (file, line) in defined_imports.items():
                if import_name not in import_usage:
                    unused_imports.append({
                        'name': import_name,
                        'file': file,
                        'line': line
                    })

            return ToolResult(
                success=True,
                output={
                    'directory': str(directory),
                    'unused_functions': unused_functions,
                    'unused_imports': unused_imports,
                    'total_functions': len(defined_functions),
                    'total_imports': len(defined_imports),
                    'note': 'This is a heuristic analysis and may have false positives'
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class SecurityScanTool(Tool):
    """Scan for common security vulnerabilities"""

    def __init__(self):
        super().__init__()
        self.name = "security_scan"
        self.description = "Scan Python code for common security issues (SQL injection, command injection, etc.)"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Python file to scan",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="security_scan",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_THREAT,
                    description="Detect security vulnerabilities in code"
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze code for security issues"
                )
            ]
        )

    async def execute(self, file_path: str) -> ToolResult:
        try:
            file = Path(file_path).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {file}")

            with open(file, 'r') as f:
                code = f.read()
                lines = code.splitlines()

            issues = []

            # Pattern-based security checks
            security_patterns = [
                (r'eval\s*\(', 'CRITICAL', 'Use of eval() - potential code injection'),
                (r'exec\s*\(', 'CRITICAL', 'Use of exec() - potential code injection'),
                (r'__import__\s*\(', 'HIGH', 'Dynamic import - review carefully'),
                (r'pickle\.loads?\s*\(', 'HIGH', 'Pickle deserialization - potential code execution'),
                (r'shell\s*=\s*True', 'CRITICAL', 'Shell=True in subprocess - command injection risk'),
                (r'os\.system\s*\(', 'HIGH', 'os.system() - command injection risk'),
                (r'md5\s*\(', 'MEDIUM', 'MD5 is cryptographically broken'),
                (r'sha1\s*\(', 'MEDIUM', 'SHA1 is cryptographically weak'),
                (r'random\.random\s*\(', 'MEDIUM', 'random module not cryptographically secure'),
                (r'input\s*\(.*\)', 'LOW', 'User input - ensure validation'),
                (r'\.format\s*\(.*sql', 'HIGH', 'String formatting with SQL - injection risk', re.IGNORECASE),
                (r'%\s*.*sql', 'HIGH', 'String interpolation with SQL - injection risk', re.IGNORECASE),
                (r'\.execute\s*\([^?]*["\'].*%', 'HIGH', 'SQL query with string formatting'),
            ]

            for i, line in enumerate(lines, 1):
                for pattern_info in security_patterns:
                    pattern = pattern_info[0]
                    severity = pattern_info[1]
                    description = pattern_info[2]
                    flags = pattern_info[3] if len(pattern_info) > 3 else 0

                    if re.search(pattern, line, flags):
                        issues.append({
                            'line': i,
                            'severity': severity,
                            'description': description,
                            'code': line.strip()
                        })

            # AST-based checks
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    # Check for hardcoded secrets (basic)
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                name = target.id.lower()
                                if any(keyword in name for keyword in ['password', 'secret', 'api_key', 'token']):
                                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                                        if len(node.value.value) > 8:  # Likely a real secret
                                            issues.append({
                                                'line': node.lineno,
                                                'severity': 'CRITICAL',
                                                'description': f'Hardcoded secret in variable: {target.id}',
                                                'code': ast.unparse(node) if hasattr(ast, 'unparse') else ''
                                            })
            except:
                pass

            # Sort by severity
            severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
            issues.sort(key=lambda x: severity_order.get(x['severity'], 4))

            return ToolResult(
                success=True,
                output={
                    'file': str(file),
                    'issues_found': len(issues),
                    'issues': issues,
                    'critical_count': len([i for i in issues if i['severity'] == 'CRITICAL']),
                    'high_count': len([i for i in issues if i['severity'] == 'HIGH']),
                    'note': 'This is a basic pattern-based scan. Use professional tools for production.'
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class FindTodosTool(Tool):
    """Find TODO/FIXME comments"""

    def __init__(self):
        super().__init__()
        self.name = "find_todos"
        self.description = "Find TODO, FIXME, HACK, and XXX comments in code"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Directory to search",
                required=True
            ),
            ToolParameter(
                name="extensions",
                type="array",
                description="File extensions to search",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="find_todos",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.PATTERN_SEARCH,
                    description="Search for TODO, FIXME, and other code markers"
                )
            ]
        )

    async def execute(self, directory_path: str, extensions: List[str] = None) -> ToolResult:
        try:
            directory = Path(directory_path).expanduser().resolve()
            if not directory.exists():
                return ToolResult(success=False, output=None, error=f"Directory not found: {directory}")

            if not extensions:
                extensions = ['.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.h']

            todos = []
            patterns = [
                (r'#.*TODO:?\s*(.*)', 'TODO'),
                (r'#.*FIXME:?\s*(.*)', 'FIXME'),
                (r'#.*HACK:?\s*(.*)', 'HACK'),
                (r'#.*XXX:?\s*(.*)', 'XXX'),
                (r'#.*BUG:?\s*(.*)', 'BUG'),
                (r'#.*NOTE:?\s*(.*)', 'NOTE'),
                (r'//.*TODO:?\s*(.*)', 'TODO'),
                (r'//.*FIXME:?\s*(.*)', 'FIXME'),
                (r'/\*.*TODO:?\s*(.*?)\*/', 'TODO'),
            ]

            # Implement more efficient search algorithm
            # Categorize and prioritize comments
            
            for ext in extensions:
                for file in directory.rglob(f'*{ext}'):
                    try:
                        with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                            for i, line in enumerate(f, 1):
                                for pattern, tag in patterns:
                                    match = re.search(pattern, line, re.IGNORECASE)
                                    if match:
                                        message = match.group(1).strip() if match.groups() else line.strip()
                                        todos.append({
                                            'file': str(file.relative_to(directory)),
                                            'line': i,
                                            'tag': tag,
                                            'message': message,
                                            'code': line.strip()
                                        })
                    except:
                        continue

            # Group by tag
            by_tag = defaultdict(list)
            for todo in todos:
                by_tag[todo['tag']].append(todo)

            return ToolResult(
                success=True,
                output={
                    'directory': str(directory),
                    'total_found': len(todos),
                    'by_tag': {tag: len(items) for tag, items in by_tag.items()},
                    'todos': todos,
                    'files_with_todos': len(set(t['file'] for t in todos))
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class CountLinesTool(Tool):
    """Count lines of code by file type"""

    def __init__(self):
        super().__init__()
        self.name = "count_lines"
        self.description = "Count total, code, comment, and blank lines by file type"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Directory to analyze",
                required=True
            ),
            ToolParameter(
                name="exclude_dirs",
                type="array",
                description="Directories to exclude (e.g., node_modules, venv)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="count_lines",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Count lines of code by file type"
                )
            ]
        )

    async def execute(self, directory_path: str, exclude_dirs: List[str] = None) -> ToolResult:
        try:
            directory = Path(directory_path).expanduser().resolve()
            if not directory.exists():
                return ToolResult(success=False, output=None, error=f"Directory not found: {directory}")

            if not exclude_dirs:
                exclude_dirs = ['node_modules', 'venv', '.venv', '__pycache__', '.git', 'dist', 'build']

            stats = defaultdict(lambda: {'total': 0, 'code': 0, 'comment': 0, 'blank': 0, 'files': 0})

            comment_patterns = {
                '.py': r'^\s*#',
                '.js': r'^\s*//',
                '.ts': r'^\s*//',
                '.jsx': r'^\s*//',
                '.tsx': r'^\s*//',
                '.java': r'^\s*//',
                '.cpp': r'^\s*//',
                '.c': r'^\s*//',
                '.h': r'^\s*//',
                '.sh': r'^\s*#',
                '.yaml': r'^\s*#',
                '.yml': r'^\s*#',
            }

            for file in directory.rglob('*'):
                # Skip excluded directories
                if any(excluded in file.parts for excluded in exclude_dirs):
                    continue

                if file.is_file():
                    ext = file.suffix
                    if not ext:
                        continue

                    try:
                        with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = f.readlines()

                        total = len(lines)
                        blank = len([l for l in lines if not l.strip()])

                        # Count comments (basic)
                        comment = 0
                        if ext in comment_patterns:
                            pattern = comment_patterns[ext]
                            comment = len([l for l in lines if re.match(pattern, l)])

                        code = total - blank - comment

                        stats[ext]['total'] += total
                        stats[ext]['code'] += code
                        stats[ext]['comment'] += comment
                        stats[ext]['blank'] += blank
                        stats[ext]['files'] += 1

                    except:
                        continue

            # Convert to regular dict and calculate totals
            result_stats = dict(stats)
            totals = {
                'total': sum(s['total'] for s in result_stats.values()),
                'code': sum(s['code'] for s in result_stats.values()),
                'comment': sum(s['comment'] for s in result_stats.values()),
                'blank': sum(s['blank'] for s in result_stats.values()),
                'files': sum(s['files'] for s in result_stats.values())
            }

            # Sort by code lines
            sorted_stats = dict(sorted(result_stats.items(), key=lambda x: x[1]['code'], reverse=True))

            return ToolResult(
                success=True,
                output={
                    'directory': str(directory),
                    'totals': totals,
                    'by_extension': sorted_stats,
                    'excluded_dirs': exclude_dirs
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
class AnalyzeComplexityTool(Tool):
    """Detailed complexity analysis"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_complexity"
        self.description = "Perform detailed cyclomatic complexity analysis on Python code"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Python file to analyze",
                required=True
            ),
            ToolParameter(
                name="complexity_threshold",
                type="number",
                description="Complexity threshold for warnings",
                required=False,
                default=10,
                min_value=1,
                max_value=100
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_complexity",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze code complexity metrics"
                ),
                CapabilityMetadata(
                    capability=Capability.ASSESS_COMPLEXITY,
                    description="Assess cyclomatic complexity of functions"
                )
            ]
        )

    async def execute(self, file_path: str, complexity_threshold: int = 10) -> ToolResult:
        try:
            file = Path(file_path).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {file}")

            with open(file, 'r') as f:
                code = f.read()

            tree = ast.parse(code)

            def calculate_complexity(node):
                """Calculate cyclomatic complexity for a function"""
                complexity = 1
                for subnode in ast.walk(node):
                    # Decision points
                    if isinstance(subnode, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                        complexity += 1
                    elif isinstance(subnode, ast.ExceptHandler):
                        complexity += 1
                    elif isinstance(subnode, ast.BoolOp):
                        complexity += len(subnode.values) - 1
                    elif isinstance(subnode, (ast.And, ast.Or)):
                        complexity += 1
                    elif isinstance(subnode, ast.comprehension):
                        complexity += 1
                        if subnode.ifs:
                            complexity += len(subnode.ifs)
                return complexity

            functions = []
            classes = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    complexity = calculate_complexity(node)
                    num_params = len(node.args.args)
                    num_lines = node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else 0

                    functions.append({
                        'name': node.name,
                        'line': node.lineno,
                        'complexity': complexity,
                        'num_parameters': num_params,
                        'num_lines': num_lines,
                        'is_async': isinstance(node, ast.AsyncFunctionDef),
                        'exceeds_threshold': complexity > complexity_threshold
                    })

                elif isinstance(node, ast.ClassDef):
                    methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    class_complexity = sum(calculate_complexity(m) for m in methods)

                    classes.append({
                        'name': node.name,
                        'line': node.lineno,
                        'num_methods': len(methods),
                        'total_complexity': class_complexity,
                        'avg_method_complexity': class_complexity / len(methods) if methods else 0
                    })

            # Sort by complexity
            functions.sort(key=lambda x: x['complexity'], reverse=True)

            # Calculate statistics
            total_complexity = sum(f['complexity'] for f in functions)
            avg_complexity = total_complexity / len(functions) if functions else 0
            high_complexity_count = len([f for f in functions if f['complexity'] > complexity_threshold])

            return ToolResult(
                success=True,
                output={
                    'file': str(file),
                    'total_functions': len(functions),
                    'total_classes': len(classes),
                    'average_complexity': round(avg_complexity, 2),
                    'max_complexity': functions[0]['complexity'] if functions else 0,
                    'high_complexity_count': high_complexity_count,
                    'complexity_threshold': complexity_threshold,
                    'functions': functions,
                    'classes': classes,
                    'recommendations': [
                        f"Refactor {f['name']} (complexity: {f['complexity']})"
                        for f in functions if f['complexity'] > complexity_threshold
                    ][:5]
                }
            )

        except SyntaxError as e:
            return ToolResult(success=False, output=None, error=f"Syntax error: {e}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class DetectCodeSmellsTool(Tool):
    """Detect code smells and anti-patterns"""

    def __init__(self):
        super().__init__()
        self.name = "detect_code_smells"
        self.description = "Detect code smells and anti-patterns in Python code"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Python file to analyze",
                required=True
            )
        ]
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="detect_code_smells",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze code structure and patterns"
                ),
                CapabilityMetadata(
                    capability=Capability.DETECT_ISSUE,
                    description="Detect code issues and problems"
                )
            ]
        )

    async def execute(self, file_path: str) -> ToolResult:
        try:
            file = Path(file_path).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {file}")

            with open(file, 'r') as f:
                code = f.read()

            tree = ast.parse(code)
            smells = []

            # Detect various code smells
            for node in ast.walk(tree):
                # Long parameter list
                if isinstance(node, ast.FunctionDef):
                    if len(node.args.args) > 5:
                        smells.append({
                            'type': 'Long Parameter List',
                            'severity': 'MEDIUM',
                            'line': node.lineno,
                            'function': node.name,
                            'message': f'Function has {len(node.args.args)} parameters (recommend <5)',
                            'fix': 'Consider grouping parameters into a dictionary or object'
                        })

                    # Long function
                    if hasattr(node, 'end_lineno'):
                        func_lines = node.end_lineno - node.lineno
                        if func_lines > 50:
                            smells.append({
                                'type': 'Long Function',
                                'severity': 'MEDIUM',
                                'line': node.lineno,
                                'function': node.name,
                                'message': f'Function is {func_lines} lines long (recommend <50)',
                                'fix': 'Break into smaller functions'
                            })

                    # Nested loops (performance smell)
                    nested_loops = 0
                    for subnode in ast.walk(node):
                        if isinstance(subnode, (ast.For, ast.While)):
                            nested_loops += 1
                    if nested_loops > 2:
                        smells.append({
                            'type': 'Deeply Nested Loops',
                            'severity': 'HIGH',
                            'line': node.lineno,
                            'function': node.name,
                            'message': f'{nested_loops} nested loops detected',
                            'fix': 'Consider list comprehensions or algorithm optimization'
                        })

                # God class (too many methods)
                elif isinstance(node, ast.ClassDef):
                    methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                    if len(methods) > 20:
                        smells.append({
                            'type': 'God Class',
                            'severity': 'HIGH',
                            'line': node.lineno,
                            'class': node.name,
                            'message': f'Class has {len(methods)} methods (recommend <20)',
                            'fix': 'Split class into smaller, focused classes'
                        })

                # Bare except
                elif isinstance(node, ast.ExceptHandler):
                    if node.type is None:
                        smells.append({
                            'type': 'Bare Except',
                            'severity': 'HIGH',
                            'line': node.lineno,
                            'message': 'Bare except clause catches all exceptions',
                            'fix': 'Catch specific exceptions'
                        })

                # Magic numbers
                elif isinstance(node, ast.Constant):
                    if isinstance(node.value, (int, float)):
                        # Skip common acceptable values
                        if node.value not in [0, 1, -1, 2, 10, 100, 1000]:
                            smells.append({
                                'type': 'Magic Number',
                                'severity': 'LOW',
                                'line': node.lineno,
                                'value': node.value,
                                'message': f'Magic number {node.value} should be a named constant',
                                'fix': 'Define as a named constant'
                            })

            # Group by type
            by_type = defaultdict(list)
            for smell in smells:
                by_type[smell['type']].append(smell)

            # Count by severity
            by_severity = defaultdict(int)
            for smell in smells:
                by_severity[smell['severity']] += 1

            return ToolResult(
                success=True,
                output={
                    'file': str(file),
                    'total_smells': len(smells),
                    'by_severity': dict(by_severity),
                    'by_type': {k: len(v) for k, v in by_type.items()},
                    'smells': sorted(smells, key=lambda x: {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}[x['severity']])[:20],
                    'critical_issues': [s for s in smells if s['severity'] == 'HIGH']
                }
            )

        except SyntaxError as e:
            return ToolResult(success=False, output=None, error=f"Syntax error: {e}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class TraceDependenciesTool(Tool):
    """Trace import dependency graph"""

    def __init__(self):
        super().__init__()
        self.name = "trace_dependencies"
        self.description = "Trace and visualize import dependencies in a Python project"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="project_path",
                type="string",
                description="Project directory path",
                required=True
            ),
            ToolParameter(
                name="max_depth",
                type="number",
                description="Maximum dependency depth to trace",
                required=False,
                default=3,
                min_value=1,
                max_value=10
            )
        ]
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="trace_dependencies",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_DEPENDENCIES,
                    description="Analyze dependencies and imports"
                )
            ]
        )

    async def execute(self, project_path: str, max_depth: int = 3) -> ToolResult:
        try:
            project = Path(project_path).expanduser().resolve()
            if not project.exists():
                return ToolResult(success=False, output=None, error=f"Project path not found: {project}")

            # Build dependency graph
            dependencies = defaultdict(set)
            all_modules = set()

            for py_file in project.rglob('*.py'):
                try:
                    with open(py_file, 'r') as f:
                        tree = ast.parse(f.read())

                    module_name = str(py_file.relative_to(project)).replace('/', '.').replace('.py', '')
                    all_modules.add(module_name)

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                dependencies[module_name].add(alias.name)
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                dependencies[module_name].add(node.module)

                except:
                    continue

            # Calculate metrics
            total_deps = sum(len(deps) for deps in dependencies.values())
            avg_deps = total_deps / len(dependencies) if dependencies else 0

            # Find modules with most dependencies
            most_deps = sorted(
                [(mod, len(deps)) for mod, deps in dependencies.items()],
                key=lambda x: x[1],
                reverse=True
            )[:10]

            # Find most imported modules
            import_counts = defaultdict(int)
            for deps in dependencies.values():
                for dep in deps:
                    import_counts[dep] += 1

            most_imported = sorted(
                import_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]

            return ToolResult(
                success=True,
                output={
                    'project': str(project),
                    'total_modules': len(all_modules),
                    'total_dependencies': total_deps,
                    'average_dependencies': round(avg_deps, 2),
                    'modules_with_most_deps': [{'module': m, 'count': c} for m, c in most_deps],
                    'most_imported_modules': [{'module': m, 'import_count': c} for m, c in most_imported],
                    'dependency_graph': {k: list(v) for k, v in dependencies.items()}
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class FindCircularImportsTool(Tool):
    """Detect circular import issues"""

    def __init__(self):
        super().__init__()
        self.name = "find_circular_imports"
        self.description = "Detect circular import dependencies in Python project"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="project_path",
                type="string",
                description="Project directory path",
                required=True
            )
        ]
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="find_circular_imports",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_ISSUE,
                    description="Detect code issues and problems"
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_DEPENDENCIES,
                    description="Analyze dependencies and imports"
                )
            ]
        )

    async def execute(self, project_path: str) -> ToolResult:
        try:
            project = Path(project_path).expanduser().resolve()
            if not project.exists():
                return ToolResult(success=False, output=None, error=f"Project path not found: {project}")

            # Build dependency graph
            graph = defaultdict(set)

            for py_file in project.rglob('*.py'):
                try:
                    with open(py_file, 'r') as f:
                        tree = ast.parse(f.read())

                    module_name = str(py_file.relative_to(project)).replace('/', '.').replace('.py', '')

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                # Only track internal imports
                                if alias.name.startswith(project.name):
                                    graph[module_name].add(alias.name)
                        elif isinstance(node, ast.ImportFrom):
                            if node.module and node.module.startswith(project.name):
                                graph[module_name].add(node.module)

                except:
                    continue

            # Detect cycles using DFS
            def find_cycles(start, path=None, visited=None):
                if path is None:
                    path = []
                if visited is None:
                    visited = set()

                path = path + [start]
                visited.add(start)
                cycles = []

                for neighbor in graph.get(start, []):
                    if neighbor in path:
                        # Found cycle
                        cycle_start = path.index(neighbor)
                        cycle = path[cycle_start:] + [neighbor]
                        cycles.append(cycle)
                    elif neighbor not in visited:
                        cycles.extend(find_cycles(neighbor, path, visited))

                return cycles

            all_cycles = []
            visited_global = set()

            for module in graph.keys():
                if module not in visited_global:
                    cycles = find_cycles(module, visited=visited_global)
                    all_cycles.extend(cycles)

            # Remove duplicate cycles
            unique_cycles = []
            seen = set()
            for cycle in all_cycles:
                cycle_key = tuple(sorted(cycle))
                if cycle_key not in seen:
                    seen.add(cycle_key)
                    unique_cycles.append(cycle)

            return ToolResult(
                success=len(unique_cycles) == 0,
                output={
                    'project': str(project),
                    'cycles_found': len(unique_cycles),
                    'circular_dependencies': [
                        {
                            'cycle': cycle,
                            'length': len(cycle) - 1,
                            'severity': 'HIGH' if len(cycle) <= 3 else 'MEDIUM'
                        }
                        for cycle in unique_cycles
                    ][:10],
                    'has_circular_imports': len(unique_cycles) > 0
                },
                error=f"Found {len(unique_cycles)} circular import(s)" if unique_cycles else None
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class AnalyzeTestCoverageReportTool(Tool):
    """Analyze existing coverage reports"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_test_coverage_report"
        self.description = "Analyze existing test coverage reports for insights"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="coverage_file",
                type="string",
                description="Path to .coverage or coverage.xml file",
                required=True
            )
        ]
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_test_coverage_report",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze code structure and patterns"
                ),
                CapabilityMetadata(
                    capability=Capability.ASSESS_COVERAGE,
                    description="Assess test coverage metrics"
                )
            ]
        )

    async def execute(self, coverage_file: str) -> ToolResult:
        try:
            file = Path(coverage_file).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"Coverage file not found: {file}")

            # Parse XML coverage report
            if file.suffix == '.xml':
                import xml.etree.ElementTree as ET
                tree = ET.parse(file)
                root = tree.getroot()

                total_lines = int(root.attrib.get('lines-valid', 0))
                covered_lines = int(root.attrib.get('lines-covered', 0))
                coverage_percent = (covered_lines / total_lines * 100) if total_lines > 0 else 0

                files_data = []
                for package in root.findall('.//package'):
                    for cls in package.findall('.//class'):
                        filename = cls.attrib.get('filename', '')
                        cls_lines = int(cls.attrib.get('line-rate', 0)) * 100

                        files_data.append({
                            'file': filename,
                            'coverage': round(cls_lines, 2)
                        })

                # Sort by coverage
                files_data.sort(key=lambda x: x['coverage'])
                uncovered_files = [f for f in files_data if f['coverage'] < 50]

                return ToolResult(
                    success=True,
                    output={
                        'coverage_file': str(file),
                        'overall_coverage': round(coverage_percent, 2),
                        'total_lines': total_lines,
                        'covered_lines': covered_lines,
                        'files_analyzed': len(files_data),
                        'poorly_covered_files': uncovered_files[:10],
                        'best_covered_files': files_data[-10:],
                        'recommendations': [
                            f"Improve coverage for {f['file']} ({f['coverage']}%)"
                            for f in uncovered_files[:5]
                        ]
                    }
                )

            else:
                return ToolResult(success=False, output=None, error="Only XML coverage reports supported")

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class FindPerformanceIssuesTool(Tool):
    """Detect performance bottlenecks"""

    def __init__(self):
        super().__init__()
        self.name = "find_performance_issues"
        self.description = "Detect potential performance bottlenecks in Python code"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_path",
                type="string",
                description="Python file to analyze",
                required=True
            )
        ]
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="find_performance_issues",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.IDENTIFY_BOTTLENECK,
                    description="Identify performance bottlenecks"
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Analyze performance characteristics"
                )
            ]
        )

    async def execute(self, file_path: str) -> ToolResult:
        try:
            file = Path(file_path).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {file}")

            with open(file, 'r') as f:
                code = f.read()

            tree = ast.parse(code)
            issues = []

            for node in ast.walk(tree):
                # Repeated string concatenation in loop
                if isinstance(node, (ast.For, ast.While)):
                    for subnode in ast.walk(node):
                        if isinstance(subnode, ast.AugAssign) and isinstance(subnode.op, ast.Add):
                            if isinstance(subnode.target, ast.Name):
                                issues.append({
                                    'type': 'String Concatenation in Loop',
                                    'severity': 'MEDIUM',
                                    'line': node.lineno,
                                    'message': 'String concatenation in loop is inefficient',
                                    'fix': 'Use list.append() and join() or use a list comprehension'
                                })

                # List comprehension that could be generator
                elif isinstance(node, ast.ListComp):
                    # Check if it's being iterated immediately
                    issues.append({
                        'type': 'List Comprehension (Consider Generator)',
                        'severity': 'LOW',
                        'line': node.lineno,
                        'message': 'Consider using generator expression if iterating once',
                        'fix': 'Use (x for x in ...) instead of [x for x in ...]'
                    })

                # Global variable access in loop
                elif isinstance(node, (ast.For, ast.While)):
                    for subnode in ast.walk(node):
                        if isinstance(subnode, ast.Global):
                            issues.append({
                                'type': 'Global Variable in Loop',
                                'severity': 'MEDIUM',
                                'line': node.lineno,
                                'message': 'Global variable access in loop reduces performance',
                                'fix': 'Assign to local variable before loop'
                            })

                # Nested function calls that could be cached
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        # Check for method calls in loops
                        issues.append({
                            'type': 'Potential Repeated Computation',
                            'severity': 'LOW',
                            'line': node.lineno,
                            'message': 'Consider caching repeated computations',
                            'fix': 'Use @lru_cache or memoization'
                        })

            # Group by type
            by_type = defaultdict(list)
            for issue in issues:
                by_type[issue['type']].append(issue)

            return ToolResult(
                success=True,
                output={
                    'file': str(file),
                    'issues_found': len(issues),
                    'by_type': {k: len(v) for k, v in by_type.items()},
                    'issues': issues[:20],
                    'high_priority': [i for i in issues if i['severity'] == 'MEDIUM'][:10]
                }
            )

        except SyntaxError as e:
            return ToolResult(success=False, output=None, error=f"Syntax error: {e}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class CheckCodeStyleConsistencyTool(Tool):
    """Check PEP 8 compliance details"""

    def __init__(self):
        super().__init__()
        self.name = "check_code_style_consistency"
        self.description = "Check Python code for PEP 8 style compliance and consistency"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Directory to check",
                required=True
            )
        ]
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="check_code_style_consistency",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze code structure and patterns"
                ),
                CapabilityMetadata(
                    capability=Capability.ASSESS_QUALITY,
                    description="Assess code quality and style"
                )
            ]
        )

    async def execute(self, directory_path: str) -> ToolResult:
        try:
            directory = Path(directory_path).expanduser().resolve()
            if not directory.exists():
                return ToolResult(success=False, output=None, error=f"Directory not found: {directory}")

            style_issues = defaultdict(int)
            files_analyzed = 0

            for py_file in directory.rglob('*.py'):
                try:
                    with open(py_file, 'r') as f:
                        lines = f.readlines()

                    files_analyzed += 1

                    for i, line in enumerate(lines, 1):
                        # Check line length
                        if len(line.rstrip()) > 88:  # Black's default
                            style_issues['lines_too_long'] += 1

                        # Check trailing whitespace
                        if line.rstrip() != line.rstrip('\n'):
                            style_issues['trailing_whitespace'] += 1

                        # Check tabs vs spaces
                        if '\t' in line:
                            style_issues['tabs_instead_of_spaces'] += 1

                        # Check multiple imports on one line
                        if line.strip().startswith('import ') and ',' in line:
                            style_issues['multiple_imports_per_line'] += 1

                        # Check naming conventions
                        if re.match(r'^\s*def\s+([A-Z]\w*)\s*\(', line):
                            style_issues['function_name_camelcase'] += 1

                        if re.match(r'^\s*class\s+([a-z_]\w*)\s*[\(:]', line):
                            style_issues['class_name_lowercase'] += 1

                except:
                    continue

            total_issues = sum(style_issues.values())

            return ToolResult(
                success=total_issues == 0,
                output={
                    'directory': str(directory),
                    'files_analyzed': files_analyzed,
                    'total_issues': total_issues,
                    'issues_by_type': dict(style_issues),
                    'compliance_score': round((1 - min(total_issues / (files_analyzed * 10), 1)) * 100, 2) if files_analyzed > 0 else 100,
                    'recommendations': [
                        f"Fix {count} instances of {issue.replace('_', ' ')}"
                        for issue, count in sorted(style_issues.items(), key=lambda x: x[1], reverse=True)[:5]
                    ]
                },
                error=f"Found {total_issues} style issues" if total_issues > 0 else None
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ASTSearchTool(Tool):
    """AST-based code search (rename-safe, symbol graph)"""

    def __init__(self):
        super().__init__()
        self.name = "ast_search"
        self.description = "Search Python code using AST for rename-safe symbol search and symbol graph analysis"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Directory to search",
                required=True
            ),
            ToolParameter(
                name="search_type",
                type="string",
                description="Type of AST search",
                required=True,
                enum=["function_def", "class_def", "function_call", "attribute_access", "import", "variable_assign"]
            ),
            ToolParameter(
                name="symbol_name",
                type="string",
                description="Symbol name to search for",
                required=True
            ),
            ToolParameter(
                name="build_symbol_graph",
                type="boolean",
                description="Build symbol graph showing relationships",
                required=False,
                default=False
            )
        ]
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="ast_search",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.AST_SEARCH,
                    description="Search code using AST structure analysis"
                )
            ]
        )

    async def execute(self, directory_path: str, search_type: str, symbol_name: str,
                     build_symbol_graph: bool = False) -> ToolResult:
        try:
            directory = Path(directory_path).expanduser().resolve()
            if not directory.exists():
                return ToolResult(success=False, output=None, error=f"Directory not found: {directory}")

            matches = []
            symbol_graph = defaultdict(lambda: {"defined_in": [], "used_in": [], "calls": [], "called_by": []})

            for py_file in directory.rglob('*.py'):
                try:
                    with open(py_file, 'r') as f:
                        code = f.read()
                        tree = ast.parse(code)

                    for node in ast.walk(tree):
                        # Function definition search
                        if search_type == "function_def" and isinstance(node, ast.FunctionDef):
                            if node.name == symbol_name:
                                matches.append({
                                    'file': str(py_file.relative_to(directory)),
                                    'line': node.lineno,
                                    'type': 'function_definition',
                                    'name': node.name,
                                    'args': [arg.arg for arg in node.args.args],
                                    'context': ast.unparse(node) if hasattr(ast, 'unparse') else f"def {node.name}(...)"
                                })
                                if build_symbol_graph:
                                    symbol_graph[symbol_name]["defined_in"].append(str(py_file.relative_to(directory)))

                        # Class definition search
                        elif search_type == "class_def" and isinstance(node, ast.ClassDef):
                            if node.name == symbol_name:
                                matches.append({
                                    'file': str(py_file.relative_to(directory)),
                                    'line': node.lineno,
                                    'type': 'class_definition',
                                    'name': node.name,
                                    'bases': [ast.unparse(base) if hasattr(ast, 'unparse') else str(base) for base in node.bases],
                                    'methods': [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                                })
                                if build_symbol_graph:
                                    symbol_graph[symbol_name]["defined_in"].append(str(py_file.relative_to(directory)))

                        # Function call search
                        elif search_type == "function_call" and isinstance(node, ast.Call):
                            if isinstance(node.func, ast.Name) and node.func.id == symbol_name:
                                matches.append({
                                    'file': str(py_file.relative_to(directory)),
                                    'line': node.lineno,
                                    'type': 'function_call',
                                    'name': symbol_name,
                                    'num_args': len(node.args)
                                })
                                if build_symbol_graph:
                                    symbol_graph[symbol_name]["used_in"].append(str(py_file.relative_to(directory)))

                        # Attribute access search
                        elif search_type == "attribute_access" and isinstance(node, ast.Attribute):
                            if node.attr == symbol_name:
                                matches.append({
                                    'file': str(py_file.relative_to(directory)),
                                    'line': node.lineno,
                                    'type': 'attribute_access',
                                    'attribute': symbol_name,
                                    'object': ast.unparse(node.value) if hasattr(ast, 'unparse') else "obj"
                                })

                        # Import search
                        elif search_type == "import":
                            if isinstance(node, ast.Import):
                                for alias in node.names:
                                    if alias.name == symbol_name or (alias.asname and alias.asname == symbol_name):
                                        matches.append({
                                            'file': str(py_file.relative_to(directory)),
                                            'line': node.lineno,
                                            'type': 'import',
                                            'module': alias.name,
                                            'alias': alias.asname
                                        })
                            elif isinstance(node, ast.ImportFrom):
                                for alias in node.names:
                                    if alias.name == symbol_name or (alias.asname and alias.asname == symbol_name):
                                        matches.append({
                                            'file': str(py_file.relative_to(directory)),
                                            'line': node.lineno,
                                            'type': 'from_import',
                                            'module': node.module,
                                            'name': alias.name,
                                            'alias': alias.asname
                                        })

                        # Variable assignment search
                        elif search_type == "variable_assign" and isinstance(node, ast.Assign):
                            for target in node.targets:
                                if isinstance(target, ast.Name) and target.id == symbol_name:
                                    matches.append({
                                        'file': str(py_file.relative_to(directory)),
                                        'line': node.lineno,
                                        'type': 'variable_assignment',
                                        'variable': symbol_name,
                                        'value_type': type(node.value).__name__
                                    })

                except SyntaxError:
                    continue
                except Exception:
                    continue

            return ToolResult(
                success=True,
                output={
                    'directory': str(directory),
                    'search_type': search_type,
                    'symbol_name': symbol_name,
                    'matches_found': len(matches),
                    'matches': matches,
                    'symbol_graph': dict(symbol_graph) if build_symbol_graph else None,
                    'rename_safe': True,
                    'note': 'AST-based search is rename-safe and finds exact symbol matches'
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class BuildDependencyGraphTool(Tool):
    """Build comprehensive dependency graph for project"""

    def __init__(self):
        super().__init__()
        self.name = "build_dependency_graph"
        self.description = "Build a comprehensive dependency graph showing module and function dependencies"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="project_path",
                type="string",
                description="Project directory path",
                required=True
            ),
            ToolParameter(
                name="include_external",
                type="boolean",
                description="Include external dependencies (not just internal modules)",
                required=False,
                default=False
            ),
            ToolParameter(
                name="max_depth",
                type="number",
                description="Maximum dependency depth to trace",
                required=False,
                default=5,
                min_value=1,
                max_value=20
            )
        ]
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="build_dependency_graph",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_DEPENDENCIES,
                    description="Analyze dependencies and imports"
                ),
                CapabilityMetadata(
                    capability=Capability.VISUALIZE,
                    description="Generate visualizations"
                )
            ]
        )

    async def execute(self, project_path: str, include_external: bool = False,
                     max_depth: int = 5) -> ToolResult:
        try:
            project = Path(project_path).expanduser().resolve()
            if not project.exists():
                return ToolResult(success=False, output=None, error=f"Project path not found: {project}")

            # Build comprehensive dependency graph
            module_graph = {}  # module -> {imports: [], imported_by: []}
            function_deps = {}  # function -> {calls: [], called_by: []}
            external_deps = set()

            # First pass: collect all module imports
            for py_file in project.rglob('*.py'):
                try:
                    with open(py_file, 'r') as f:
                        tree = ast.parse(f.read())

                    module_name = str(py_file.relative_to(project)).replace('/', '.').replace('.py', '')

                    if module_name not in module_graph:
                        module_graph[module_name] = {'imports': [], 'imported_by': [], 'file': str(py_file.relative_to(project))}

                    # Collect imports
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imp_name = alias.name
                                if include_external or imp_name.startswith(project.name):
                                    module_graph[module_name]['imports'].append(imp_name)
                                    if not imp_name.startswith(project.name):
                                        external_deps.add(imp_name)

                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imp_name = node.module
                                if include_external or imp_name.startswith(project.name):
                                    module_graph[module_name]['imports'].append(imp_name)
                                    if not imp_name.startswith(project.name):
                                        external_deps.add(imp_name)

                except:
                    continue

            # Second pass: build reverse dependencies
            for module, data in module_graph.items():
                for imported in data['imports']:
                    if imported in module_graph:
                        if 'imported_by' not in module_graph[imported]:
                            module_graph[imported]['imported_by'] = []
                        module_graph[imported]['imported_by'].append(module)

            # Calculate metrics
            total_modules = len(module_graph)
            total_internal_deps = sum(len(d['imports']) for d in module_graph.values())
            avg_deps_per_module = total_internal_deps / total_modules if total_modules > 0 else 0

            # Find modules with most dependencies
            most_dependent = sorted(
                [(mod, len(data['imports'])) for mod, data in module_graph.items()],
                key=lambda x: x[1],
                reverse=True
            )[:10]

            # Find most depended-upon modules (hubs)
            dependency_hubs = sorted(
                [(mod, len(data.get('imported_by', []))) for mod, data in module_graph.items()],
                key=lambda x: x[1],
                reverse=True
            )[:10]

            # Detect potential circular dependencies
            circular_deps = []
            for module, data in module_graph.items():
                for imported in data['imports']:
                    if imported in module_graph:
                        if module in module_graph[imported]['imports']:
                            pair = tuple(sorted([module, imported]))
                            if pair not in [tuple(sorted(c)) for c in circular_deps]:
                                circular_deps.append([module, imported])

            return ToolResult(
                success=True,
                output={
                    'project': str(project),
                    'total_modules': total_modules,
                    'total_dependencies': total_internal_deps,
                    'avg_dependencies_per_module': round(avg_deps_per_module, 2),
                    'external_dependencies': len(external_deps),
                    'external_deps_list': sorted(list(external_deps))[:50],
                    'dependency_graph': module_graph,
                    'most_dependent_modules': [{'module': m, 'dep_count': c} for m, c in most_dependent],
                    'dependency_hubs': [{'module': m, 'used_by_count': c} for m, c in dependency_hubs],
                    'circular_dependencies': circular_deps,
                    'has_circular_deps': len(circular_deps) > 0
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ExtractCallGraphTool(Tool):
    """Extract function call graph from codebase"""

    def __init__(self):
        super().__init__()
        self.name = "extract_call_graph"
        self.description = "Extract and analyze function call graph showing which functions call which other functions"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Directory to analyze",
                required=True
            ),
            ToolParameter(
                name="entry_point",
                type="string",
                description="Entry point function to start call graph from (optional)",
                required=False
            ),
            ToolParameter(
                name="max_depth",
                type="number",
                description="Maximum call depth to trace",
                required=False,
                default=10,
                min_value=1,
                max_value=50
            )
        ]
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="extract_call_graph",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_CODE,
                    description="Analyze code structure and patterns"
                )
            ]
        )

    async def execute(self, directory_path: str, entry_point: Optional[str] = None,
                     max_depth: int = 10) -> ToolResult:
        try:
            directory = Path(directory_path).expanduser().resolve()
            if not directory.exists():
                return ToolResult(success=False, output=None, error=f"Directory not found: {directory}")

            # Build call graph
            functions = {}  # function_name -> {file, line, calls: [], called_by: []}
            call_graph = defaultdict(set)  # function -> set of functions it calls

            # First pass: collect all function definitions and their calls
            for py_file in directory.rglob('*.py'):
                try:
                    with open(py_file, 'r') as f:
                        code = f.read()
                        tree = ast.parse(code)

                    # Find all function definitions
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            func_name = node.name
                            if func_name not in functions:
                                functions[func_name] = {
                                    'file': str(py_file.relative_to(directory)),
                                    'line': node.lineno,
                                    'calls': [],
                                    'called_by': [],
                                    'params': len(node.args.args),
                                    'is_async': isinstance(node, ast.AsyncFunctionDef)
                                }

                            # Find function calls within this function
                            for subnode in ast.walk(node):
                                if isinstance(subnode, ast.Call):
                                    if isinstance(subnode.func, ast.Name):
                                        called_func = subnode.func.id
                                        call_graph[func_name].add(called_func)

                except SyntaxError:
                    continue
                except Exception:
                    continue

            # Build reverse call graph (called_by relationships)
            for caller, callees in call_graph.items():
                if caller in functions:
                    functions[caller]['calls'] = list(callees)
                for callee in callees:
                    if callee in functions:
                        functions[callee]['called_by'].append(caller)

            # If entry point specified, trace call graph from there
            call_trace = None
            if entry_point and entry_point in functions:
                call_trace = self._trace_calls(entry_point, call_graph, max_depth)

            # Calculate metrics
            total_functions = len(functions)
            total_calls = sum(len(calls) for calls in call_graph.values())
            avg_calls_per_func = total_calls / total_functions if total_functions > 0 else 0

            # Find most called functions (hot spots)
            hot_spots = sorted(
                [(func, len(data['called_by'])) for func, data in functions.items()],
                key=lambda x: x[1],
                reverse=True
            )[:10]

            # Find functions that call many others (high fan-out)
            high_fanout = sorted(
                [(func, len(data['calls'])) for func, data in functions.items()],
                key=lambda x: x[1],
                reverse=True
            )[:10]

            # Find leaf functions (call nothing)
            leaf_functions = [func for func, data in functions.items() if not data['calls']]

            # Find entry functions (called by nothing, but call others)
            entry_functions = [func for func, data in functions.items()
                             if not data['called_by'] and data['calls']]

            return ToolResult(
                success=True,
                output={
                    'directory': str(directory),
                    'total_functions': total_functions,
                    'total_calls': total_calls,
                    'avg_calls_per_function': round(avg_calls_per_func, 2),
                    'call_graph': {func: list(calls) for func, calls in call_graph.items()},
                    'functions': functions,
                    'hot_spots': [{'function': f, 'called_by_count': c} for f, c in hot_spots],
                    'high_fanout': [{'function': f, 'calls_count': c} for f, c in high_fanout],
                    'leaf_functions': leaf_functions[:20],
                    'entry_functions': entry_functions[:20],
                    'call_trace_from_entry': call_trace,
                    'entry_point': entry_point
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    def _trace_calls(self, func: str, call_graph: dict, max_depth: int, depth: int = 0, visited: Set[str] = None) -> List:
        """Trace function calls from entry point"""
        if visited is None:
            visited = set()

        if depth >= max_depth or func in visited:
            return []

        visited.add(func)
        trace = {'function': func, 'depth': depth, 'calls': []}

        for called in call_graph.get(func, []):
            trace['calls'].append(self._trace_calls(called, call_graph, max_depth, depth + 1, visited.copy()))

        return trace


class SearchSecretsAndPIITool(Tool):
    """Security-aware search for secrets and PII patterns"""

    def __init__(self):
        super().__init__()
        self.name = "search_secrets_pii"
        self.description = "Search for secrets (API keys, tokens, passwords) and PII (emails, SSN, credit cards) in codebase and files"
        self.category = ToolCategory.SEARCH
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="directory_path",
                type="string",
                description="Directory to search",
                required=True
            ),
            ToolParameter(
                name="search_types",
                type="array",
                description="Types to search for",
                required=False
            ),
            ToolParameter(
                name="exclude_files",
                type="array",
                description="File patterns to exclude (e.g., ['*.test.js', 'test_*.py'])",
                required=False
            )
        ]
        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="search_secrets_pii",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_THREAT,
                    description="Detect security threats"
                ),
                CapabilityMetadata(
                    capability=Capability.PATTERN_SEARCH,
                    description="Search for secrets and PII using pattern matching"
                )
            ]
        )

    async def execute(self, directory_path: str, search_types: List[str] = None,
                     exclude_files: List[str] = None) -> ToolResult:
        try:
            directory = Path(directory_path).expanduser().resolve()
            if not directory.exists():
                return ToolResult(success=False, output=None, error=f"Directory not found: {directory}")

            if not search_types:
                search_types = ["api_keys", "passwords", "tokens", "email", "ssn", "credit_card", "private_keys"]

            if not exclude_files:
                exclude_files = ['*.test.*', 'test_*', '*_test.*', '*.min.js', '*.min.css', 'node_modules/*', '.git/*']

            # Detection patterns
            patterns = {
                "api_keys": [
                    (r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})["\']', 'API Key'),
                    (r'(?i)(secret[_-]?key|secretkey)\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})["\']', 'Secret Key'),
                    (r'(?i)(access[_-]?token|accesstoken)\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})["\']', 'Access Token'),
                ],
                "passwords": [
                    (r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']([^"\'\s]{8,})["\']', 'Hardcoded Password'),
                ],
                "tokens": [
                    (r'(?i)(bearer|token)\s+([a-zA-Z0-9_\-\.]{40,})', 'Bearer Token'),
                    (r'(?i)(jwt|json[_-]?web[_-]?token)\s*[:=]\s*["\']([a-zA-Z0-9_\-\.]{40,})["\']', 'JWT Token'),
                ],
                "email": [
                    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', 'Email Address'),
                ],
                "ssn": [
                    (r'\b\d{3}-\d{2}-\d{4}\b', 'Social Security Number'),
                    (r'\b\d{9}\b', 'SSN (no dashes)'),
                ],
                "credit_card": [
                    (r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b', 'Credit Card Number'),
                ],
                "private_keys": [
                    (r'-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----', 'Private Key'),
                    (r'-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----', 'OpenSSH Private Key'),
                ]
            }

            findings = []
            files_scanned = 0

            # Search through files
            for file_path in directory.rglob('*'):
                if not file_path.is_file():
                    continue

                # Check exclusions
                if any(file_path.match(pattern) for pattern in exclude_files):
                    continue

                # Only scan text files
                if file_path.suffix not in ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.txt',
                                            '.json', '.xml', '.yaml', '.yml', '.env', '.config', '.cfg']:
                    continue

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        lines = content.split('\n')

                    files_scanned += 1

                    for search_type in search_types:
                        if search_type not in patterns:
                            continue

                        for pattern, description in patterns[search_type]:
                            for i, line in enumerate(lines, 1):
                                matches = re.finditer(pattern, line)
                                for match in matches:
                                    # Extract the sensitive value (if captured)
                                    value = match.group(2) if match.groups() and len(match.groups()) >= 2 else match.group(0)

                                    # Mask the value for output
                                    masked_value = value[:4] + '*' * (len(value) - 8) + value[-4:] if len(value) > 8 else '*' * len(value)

                                    findings.append({
                                        'type': search_type,
                                        'description': description,
                                        'file': str(file_path.relative_to(directory)),
                                        'line': i,
                                        'masked_value': masked_value,
                                        'severity': self._get_severity(search_type),
                                        'context': line.strip()[:100]
                                    })

                except Exception:
                    continue

            # Group findings by severity
            by_severity = defaultdict(int)
            for finding in findings:
                by_severity[finding['severity']] += 1

            # Group by type
            by_type = defaultdict(int)
            for finding in findings:
                by_type[finding['type']] += 1

            return ToolResult(
                success=True,
                output={
                    'directory': str(directory),
                    'files_scanned': files_scanned,
                    'findings_count': len(findings),
                    'findings': findings,
                    'by_severity': dict(by_severity),
                    'by_type': dict(by_type),
                    'critical_findings': [f for f in findings if f['severity'] == 'CRITICAL'][:10],
                    'high_findings': [f for f in findings if f['severity'] == 'HIGH'][:10],
                    'recommendations': self._get_recommendations(findings)
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    def _get_severity(self, search_type: str) -> str:
        """Determine severity based on secret type"""
        severity_map = {
            'api_keys': 'CRITICAL',
            'passwords': 'CRITICAL',
            'tokens': 'CRITICAL',
            'private_keys': 'CRITICAL',
            'credit_card': 'CRITICAL',
            'ssn': 'CRITICAL',
            'email': 'MEDIUM'
        }
        return severity_map.get(search_type, 'MEDIUM')

    def _get_recommendations(self, findings: List[Dict]) -> List[str]:
        """Generate recommendations based on findings"""
        recommendations = []

        if any(f['type'] in ['api_keys', 'passwords', 'tokens'] for f in findings):
            recommendations.append("Move secrets to environment variables or secure vault (e.g., AWS Secrets Manager, HashiCorp Vault)")

        if any(f['type'] == 'private_keys' for f in findings):
            recommendations.append("Never commit private keys to version control. Use .gitignore and rotate compromised keys immediately")

        if any(f['type'] in ['credit_card', 'ssn'] for f in findings):
            recommendations.append("Remove PII from codebase. If test data is needed, use fake/synthetic data generators")

        if any(f['type'] == 'email' for f in findings):
            recommendations.append("Review email addresses - ensure they're not exposing real user data in test files")

        return recommendations
