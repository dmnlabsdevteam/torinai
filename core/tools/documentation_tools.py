#!/usr/bin/env python3
"""
Documentation Tools
===================
AI-powered documentation generation tools

Purpose:
- Generate code documentation automatically
- Create README files
- Generate API documentation
- Analyze and document codebase
"""

import asyncio
import logging
import os
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from pathlib import Path

# Import API registry
from core.integration.external_api_integration_manager import (
    get_api_manager, APIProvider
)

logger = logging.getLogger(__name__)


@dataclass
class DocumentationConfig:
    """Documentation generation configuration"""
    include_examples: bool = True
    include_types: bool = True
    include_docstrings: bool = True
    style: str = "google"  # google, numpy, sphinx
    output_format: str = "markdown"  # markdown, rst, html


@dataclass
class DocumentationResult:
    """Documentation generation result"""
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


class DocumentationTools:
    """
    AI-Powered Documentation Tools

    Purpose:
    - Generate documentation using LLM APIs
    - Use API registry for provider management
    - Support multiple documentation styles
    - Extract and analyze code structure

    Usage:
        docs = DocumentationTools()
        result = await docs.generate_function_docs(code, "my_function")
    """

    def __init__(self, config: DocumentationConfig = None):
        self.config = config or DocumentationConfig()
        self.api_manager = get_api_manager()

        logger.info("DocumentationTools initialized")

    async def generate_function_docs(
        self,
        code: str,
        function_name: str = None,
        language: str = "python"
    ) -> DocumentationResult:
        """
        Generate documentation for a function

        Args:
            code: Source code containing the function
            function_name: Name of function to document (optional)
            language: Programming language

        Returns:
            DocumentationResult with generated documentation
        """
        try:
            logger.info(f"Generating function docs for {function_name or 'code'}")

            # Extract function if name provided
            if function_name:
                function_code = self._extract_function(code, function_name, language)
            else:
                function_code = code

            # Get code analysis
            analysis = self._analyze_code(function_code, language)

            # Build prompt for LLM
            prompt = f"""Generate comprehensive documentation for this {language} function:

```{language}
{function_code}
```

Include:
- Purpose and description
- Parameters with types
- Return value
- Usage example (if applicable)
- Any important notes

Format: {self.config.style} style docstring"""

            # Call LLM via API registry
            doc_content = await self._call_llm_for_docs(prompt)

            # If response contains code blocks, extract documentation
            if '```' in doc_content:
                doc_content = self._extract_from_code_block(doc_content)

            return DocumentationResult(
                content=doc_content,
                metadata={
                    "function_name": function_name,
                    "language": language,
                    "style": self.config.style,
                    "analysis": analysis
                },
                success=True
            )

        except Exception as e:
            logger.error(f"Failed to generate function docs: {e}")
            return DocumentationResult(
                content="",
                success=False,
                error=str(e)
            )

    async def generate_class_docs(
        self,
        code: str,
        class_name: str = None,
        language: str = "python"
    ) -> DocumentationResult:
        """
        Generate documentation for a class

        Args:
            code: Source code containing the class
            class_name: Name of class to document
            language: Programming language

        Returns:
            DocumentationResult with generated documentation
        """
        try:
            logger.info(f"Generating class docs for {class_name or 'code'}")

            # Extract class if name provided
            if class_name:
                class_code = self._extract_class(code, class_name, language)
            else:
                class_code = code

            # Analyze class structure
            analysis = self._analyze_code(class_code, language)

            prompt = f"""Generate comprehensive documentation for this {language} class:

```{language}
{class_code}
```

Include:
- Class purpose and description
- Constructor parameters
- Public methods overview
- Usage example
- Important attributes

Format: {self.config.style} style"""

            doc_content = await self._call_llm_for_docs(prompt)

            if '```' in doc_content:
                doc_content = self._extract_from_code_block(doc_content)

            return DocumentationResult(
                content=doc_content,
                metadata={
                    "class_name": class_name,
                    "language": language,
                    "analysis": analysis
                },
                success=True
            )

        except Exception as e:
            logger.error(f"Failed to generate class docs: {e}")
            return DocumentationResult(
                content="",
                success=False,
                error=str(e)
            )

    async def generate_module_docs(
        self,
        file_path: str
    ) -> DocumentationResult:
        """
        Generate documentation for an entire module/file

        Args:
            file_path: Path to source file

        Returns:
            DocumentationResult with module documentation
        """
        try:
            logger.info(f"Generating module docs for {file_path}")

            # Read file
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()

            # Determine language from file extension
            language = self._get_language_from_path(file_path)

            # Analyze module structure
            analysis = self._analyze_code(code, language)

            prompt = f"""Generate comprehensive module documentation for this {language} file:

File: {Path(file_path).name}

```{language}
{code[:3000]}  # First 3000 chars
```

Include:
- Module purpose and overview
- Key classes and functions
- Usage examples
- Dependencies
- Important notes

Format: Markdown"""

            doc_content = await self._call_llm_for_docs(prompt)

            return DocumentationResult(
                content=doc_content,
                metadata={
                    "file_path": file_path,
                    "language": language,
                    "analysis": analysis
                },
                success=True
            )

        except Exception as e:
            logger.error(f"Failed to generate module docs: {e}")
            return DocumentationResult(
                content="",
                success=False,
                error=str(e)
            )

    async def generate_readme(
        self,
        project_path: str,
        project_name: str = None
    ) -> DocumentationResult:
        """
        Generate README.md for a project

        Args:
            project_path: Path to project directory
            project_name: Project name (optional)

        Returns:
            DocumentationResult with README content
        """
        try:
            logger.info(f"Generating README for {project_path}")

            # Analyze project structure
            structure = self._analyze_project_structure(project_path)

            if not project_name:
                project_name = Path(project_path).name

            prompt = f"""Generate a comprehensive README.md for this project:

Project: {project_name}

Structure:
{structure}

Include:
1. Project Title and Description
2. Features
3. Installation
4. Usage Examples
5. Configuration
6. API Documentation (if applicable)
7. Contributing
8. License

Format: Professional GitHub README.md"""

            readme_content = await self._call_llm_for_docs(prompt)

            return DocumentationResult(
                content=readme_content,
                metadata={
                    "project_name": project_name,
                    "project_path": project_path
                },
                success=True
            )

        except Exception as e:
            logger.error(f"Failed to generate README: {e}")
            return DocumentationResult(
                content="",
                success=False,
                error=str(e)
            )

    async def generate_api_docs(
        self,
        code: str,
        api_type: str = "REST"
    ) -> DocumentationResult:
        """
        Generate API documentation

        Args:
            code: API source code
            api_type: Type of API (REST, GraphQL, etc.)

        Returns:
            DocumentationResult with API documentation
        """
        try:
            logger.info(f"Generating {api_type} API docs")

            prompt = f"""Generate comprehensive {api_type} API documentation for this code:

```python
{code}
```

Include:
- API Overview
- Endpoints
- Request/Response formats
- Authentication
- Error codes
- Usage examples

Format: Markdown with code examples"""

            api_docs = await self._call_llm_for_docs(prompt)

            return DocumentationResult(
                content=api_docs,
                metadata={
                    "api_type": api_type
                },
                success=True
            )

        except Exception as e:
            logger.error(f"Failed to generate API docs: {e}")
            return DocumentationResult(
                content="",
                success=False,
                error=str(e)
            )

    async def _call_llm_for_docs(self, prompt: str) -> str:
        """
        Call LLM via API registry to generate documentation

        Args:
            prompt: Documentation generation prompt

        Returns:
            Generated documentation text
        """
        try:
            # Get recommended provider from API registry
            provider = await self.api_manager.get_provider_recommendation("chat")

            if not provider:
                logger.warning("No API provider available, using fallback")
                return self._fallback_documentation(prompt)

            # Call API through registry
            model = self.config.get('documentation_model', 'gpt-4')

            from core.services.unified_llm import get_llm_service
            llm = get_llm_service()

            response = await self.api_manager.call_api(
                provider=provider,
                endpoint="chat/completions",
                method="POST",
                data={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": llm.system_prompts.get("documentation_expert")
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": 0.3,  # Lower temperature for consistent docs
                    "max_tokens": 2000
                }
            )

            # Extract content from response
            if 'error' not in response:
                # Parse OpenAI-style response
                if 'choices' in response:
                    return response['choices'][0]['message']['content']
                # Fallback to whole response
                return str(response)

            logger.warning(f"API call failed: {response.get('error')}")
            return self._fallback_documentation(prompt)

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return self._fallback_documentation(prompt)

    def _fallback_documentation(self, prompt: str) -> str:
        """Generate basic documentation when LLM unavailable"""
        return """# Documentation

This documentation was generated automatically.

Please add detailed documentation for this code.

## Usage

```python
# Add usage examples here
```

## Notes

- Auto-generated documentation
- LLM service unavailable
- Please review and enhance
"""

    def _analyze_code(self, code: str, language: str) -> Dict[str, Any]:
        """Analyze code structure"""
        lines = code.split('\n')

        analysis = {
            "lines_of_code": len(lines),
            "language": language,
            "has_docstring": '"""' in code or "'''" in code,
            "has_comments": '#' in code or '//' in code
        }

        # Python-specific analysis
        if language == "python":
            analysis["functions"] = len(re.findall(r'\bdef\s+\w+', code))
            analysis["classes"] = len(re.findall(r'\bclass\s+\w+', code))
            analysis["imports"] = len(re.findall(r'^\s*import\s+|^\s*from\s+', code, re.MULTILINE))

        return analysis

    def _extract_function(self, code: str, function_name: str, language: str) -> str:
        """Extract a specific function from code"""
        if language == "python":
            # Simple extraction - in production, use AST
            pattern = rf'def\s+{function_name}\s*\([^)]*\):[^\n]*\n(?:(?:    |\t).*\n)*'
            match = re.search(pattern, code)
            if match:
                return match.group(0)

        # Fallback: return whole code
        return code

    def _extract_class(self, code: str, class_name: str, language: str) -> str:
        """Extract a specific class from code"""
        if language == "python":
            # Simple extraction - in production, use AST
            pattern = rf'class\s+{class_name}[^:]*:[^\n]*\n(?:(?:    |\t).*\n)*'
            match = re.search(pattern, code)
            if match:
                return match.group(0)

        return code

    def _extract_from_code_block(self, text: str) -> str:
        """Extract content from markdown code block"""
        if '```' in text:
            parts = text.split('```')
            if len(parts) >= 3:
                return parts[1].strip()
        return text

    def _get_language_from_path(self, file_path: str) -> str:
        """Determine language from file extension"""
        ext = Path(file_path).suffix.lower()
        mapping = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.go': 'go',
            '.java': 'java',
            '.rs': 'rust',
            '.cpp': 'cpp',
            '.c': 'c'
        }
        return mapping.get(ext, 'unknown')

    def _analyze_project_structure(self, project_path: str, max_depth: int = 3) -> str:
        """Analyze project directory structure"""
        try:
            structure_lines = []
            path = Path(project_path)

            for root, dirs, files in os.walk(path):
                level = len(Path(root).relative_to(path).parts)
                if level >= max_depth:
                    continue

                indent = "  " * level
                structure_lines.append(f"{indent}{Path(root).name}/")

                for file in files[:10]:  # Limit files shown
                    structure_lines.append(f"{indent}  {file}")

                if len(structure_lines) > 50:  # Limit total lines
                    structure_lines.append("  ... (truncated)")
                    break

            return "\n".join(structure_lines)

        except Exception as e:
            logger.error(f"Failed to analyze project structure: {e}")
            return "Unable to analyze project structure"


# Singleton instance
_documentation_tools = None


def get_documentation_tools() -> DocumentationTools:
    """Get global documentation tools instance"""
    global _documentation_tools
    if _documentation_tools is None:
        _documentation_tools = DocumentationTools()
    return _documentation_tools


# CLI test
async def main():
    """Test documentation tools"""
    logging.basicConfig(level=logging.INFO)

    docs = get_documentation_tools()

    # Test function documentation
    sample_code = """
def calculate_total(items: List[int], tax_rate: float = 0.1) -> float:
    subtotal = sum(items)
    tax = subtotal * tax_rate
    return subtotal + tax
"""

    print("\n=== Documentation Tools Test ===")

    result = await docs.generate_function_docs(sample_code, "calculate_total")
    print(f"\nGenerated docs: {result.success}")
    print(f"Content preview: {result.content[:200]}...")


if __name__ == "__main__":
    asyncio.run(main())


# ============================================================================
# Tool Classes for Agent Use
# ============================================================================

from core.tools.tool_registry import Tool, ToolCategory, ToolResult, ToolParameter
from core.tools.capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata, RiskLevel


class GenerateReadmeTool(Tool):
    """Production-ready README generation using LLM and project analysis"""

    def __init__(self):
        super().__init__()
        self.name = "generate_readme"
        self.description = "Generate a comprehensive README.md by analyzing project structure using LLM"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="project_path",
                type="string",
                description="Path to the project directory",
                required=True
            ),
            ToolParameter(
                name="project_name",
                type="string",
                description="Name of the project (optional, inferred from directory)",
                required=False
            ),
            ToolParameter(
                name="description",
                type="string",
                description="Project description (optional, will be inferred)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_readme",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="GenerateReadme capability"
                ),
                CapabilityMetadata(
                    capability=Capability.GENERATE_DOCS,
                    description="Generate comprehensive documentation",
                    input_types=["source_code", "config"],
                    output_types=["docs"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate comprehensive README using project analysis and LLM"""
        try:
            from core.services.unified_llm import get_llm_service

            project_path = kwargs.get("project_path", ".")
            project_name = kwargs.get("project_name") or Path(project_path).name
            description = kwargs.get("description", "")

            # Analyze project structure
            structure_info = self._analyze_project(project_path)

            # Build comprehensive prompt
            prompt = f"""Generate a professional README.md for this project:

Project Name: {project_name}
{f'Description: {description}' if description else ''}

Project Structure Analysis:
{structure_info['structure']}

Key Files Found:
{', '.join(structure_info['key_files'])}

Dependencies Found:
{', '.join(structure_info['dependencies'])}

Requirements:
- Professional GitHub-style README
- Include badges (build, coverage, license)
- Installation instructions
- Usage examples with code
- API/Features documentation
- Contributing guidelines
- License information
- Proper sections and formatting

Return only the README.md content in markdown format."""

            llm = get_llm_service()
            response = await llm.generate(prompt, max_tokens=3072, temperature=0.3)
            readme_content = response.get('content', '').strip()

            # Extract from code blocks if LLM wrapped it
            if '```markdown' in readme_content:
                readme_content = readme_content.split('```markdown')[1].split('```')[0].strip()
            elif '```' in readme_content:
                parts = readme_content.split('```')
                if len(parts) >= 3:
                    readme_content = parts[1].strip()

            return ToolResult(
                success=True,
                output={
                    "content": readme_content,
                    "filename": "README.md",
                    "project_name": project_name,
                    "analysis": structure_info
                }
            )
        except Exception as e:
            logger.error(f"Failed to generate README: {e}")
            # Fallback to template
            # A TEMPLATE IS NOT THE ARTEFACT. Returning success=True here
            # handed the caller boilerplate and told them it was generated
            # from their input. The template is still returned so it can be
            # used deliberately, but the result says what it is.
            fallback = self._generate_fallback_readme(
                kwargs.get("project_name", "Project"),
                kwargs.get("description", "A software project")
            )
            return ToolResult(
                success=False,
                error=f"README generation failed ({e}); a generic template is attached",
                output={"content": fallback, "filename": "README.md", "method": "template"}
            )

    def _analyze_project(self, project_path: str) -> dict:
        """Analyze project structure for README generation"""
        path = Path(project_path)
        analysis = {
            "structure": "",
            "key_files": [],
            "dependencies": []
        }

        try:
            # Find key files
            key_patterns = {
                "setup.py": "Python package",
                "pyproject.toml": "Modern Python project",
                "package.json": "Node.js project",
                "Cargo.toml": "Rust project",
                "go.mod": "Go project",
                "requirements.txt": "Python dependencies",
                "Dockerfile": "Docker support",
                ".github/workflows": "CI/CD",
                "tests/": "Test suite",
                "docs/": "Documentation"
            }

            for pattern, desc in key_patterns.items():
                if (path / pattern).exists():
                    analysis["key_files"].append(f"{pattern} ({desc})")

            # Read dependencies
            if (path / "requirements.txt").exists():
                with open(path / "requirements.txt", 'r') as f:
                    deps = [line.split('==')[0].strip() for line in f if line.strip() and not line.startswith('#')]
                    analysis["dependencies"] = deps[:10]  # Limit to top 10

            # Build structure string
            structure_lines = []
            for item in sorted(path.iterdir())[:15]:
                if item.name.startswith('.'):
                    continue
                structure_lines.append(f"- {item.name}{'/' if item.is_dir() else ''}")
            analysis["structure"] = "\n".join(structure_lines)

        except Exception as e:
            logger.warning(f"Project analysis partial failure: {e}")

        return analysis

    def _generate_fallback_readme(self, project_name: str, description: str) -> str:
        """Generate fallback README when LLM unavailable"""
        return f"""# {project_name}

{description}

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```python
# Add usage examples here
```

## Features

- Feature documentation needed
- See source code for details

## Contributing

Contributions welcome! Please open an issue or PR.

## License

See LICENSE file for details.
"""


class GenerateAPIDocsTool(Tool):
    """Generate API documentation from code"""

    def __init__(self):
        super().__init__()
        self.name = "generate_api_docs"
        self.description = "Generate API documentation from source code"
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Source code to document",
                required=True
            ),
            ToolParameter(
                name="format",
                type="string",
                description="Documentation format (markdown, html, rst)",
                required=False,
                default="markdown"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_api_docs",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="GenerateAPIDocs capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate API docs"""
        try:
            code = kwargs.get("code", "")
            format_type = kwargs.get("format", "markdown")

            # Use LLM for intelligent documentation generation
            from core.services.unified_llm import get_llm_service
            llm = get_llm_service()

            prompt = f"""Generate API documentation for this code in {format_type} format:

```python
{code}
```

Include:
- Function/class descriptions
- Parameters and return types
- Usage examples
- Notes and warnings

Return only the documentation, no code."""

            result = await llm.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=2048,
                agent_type="documentation_expert"
            )

            response = result.get("content", "")

            return ToolResult(
                success=True,
                output={"documentation": response, "format": format_type}
            )
        except Exception as e:
            logger.error(f"Failed to generate API docs: {e}")
            # Fallback to basic documentation
            # A TEMPLATE IS NOT THE ARTEFACT. Returning success=True here
            # handed the caller boilerplate and told them it was generated
            # from their input. The template is still returned so it can be
            # used deliberately, but the result says what it is.
            docs = f"# API Documentation\n\n## Overview\n\nCode documentation for the provided code.\n"
            return ToolResult(
                success=False,
                error=f"API documentation generation failed ({e}); a stub heading is attached",
                output={"documentation": docs, "format": "markdown", "method": "template"}
            )


class AnalyzeCodeQualityTool(Tool):
    """Analyze code quality and provide metrics"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_code_quality"
        self.description = "Analyze code quality and provide detailed metrics"
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Source code to analyze",
                required=True
            ),
            ToolParameter(
                name="include_suggestions",
                type="boolean",
                description="Include improvement suggestions",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_code_quality",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="AnalyzeCodeQuality capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Analyze code quality"""
        try:
            code = kwargs.get("code", "")
            include_suggestions = kwargs.get("include_suggestions", True)

            # Basic quality metrics
            lines = code.split('\n')
            total_lines = len(lines)
            code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
            comment_lines = len([l for l in lines if l.strip().startswith('#')])

            # Calculate metrics
            quality_metrics = {
                "total_lines": total_lines,
                "code_lines": code_lines,
                "comment_lines": comment_lines,
                "comment_ratio": comment_lines / max(code_lines, 1),
                "complexity_score": min(10, code_lines / 10),  # Simple heuristic
                "maintainability_score": 8.5,  # Placeholder
                "issues": []
            }

            # Basic quality checks
            if quality_metrics["comment_ratio"] < 0.1:
                quality_metrics["issues"].append("Low comment coverage - consider adding more documentation")

            if code_lines > 500:
                quality_metrics["issues"].append("File is large - consider refactoring into smaller modules")

            if include_suggestions:
                quality_metrics["suggestions"] = [
                    "Add type hints to function parameters",
                    "Consider adding unit tests",
                    "Review naming conventions for clarity"
                ]

            return ToolResult(
                success=True,
                output=quality_metrics
            )
        except Exception as e:
            logger.error(f"Failed to analyze code quality: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class ExtractDocstringsTool(Tool):
    """Extract docstrings from Python code"""

    def __init__(self):
        super().__init__()
        self.name = "extract_docstrings"
        self.description = "Extract all docstrings from Python code"
        self.parameters = [
            ToolParameter(
                name="code",
                type="string",
                description="Python source code to extract docstrings from",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="extract_docstrings",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="ExtractDocstrings capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Extract docstrings"""
        try:
            code = kwargs.get("code", "")
            import ast

            # Parse code and extract docstrings
            tree = ast.parse(code)
            docstrings = {}

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                    docstring = ast.get_docstring(node)
                    if docstring:
                        name = getattr(node, 'name', 'module')
                        docstrings[name] = docstring

            return ToolResult(
                success=True,
                output={"docstrings": docstrings, "count": len(docstrings)}
            )
        except Exception as e:
            logger.error(f"Failed to extract docstrings: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class GenerateChangelogTool(Tool):
    """Production-ready CHANGELOG generation from git history using LLM"""

    def __init__(self):
        super().__init__()
        self.name = "generate_changelog"
        self.description = "Generate CHANGELOG.md from git commit history with intelligent categorization"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="repo_path",
                type="string",
                description="Path to git repository",
                required=False,
                default="."
            ),
            ToolParameter(
                name="since_tag",
                type="string",
                description="Generate changelog since this git tag (optional)",
                required=False
            ),
            ToolParameter(
                name="max_commits",
                type="number",
                description="Maximum number of commits to analyze",
                required=False,
                default=100
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_changelog",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="GenerateChangelog capability"
                ),
                CapabilityMetadata(
                    capability=Capability.GENERATE_REPORT,
                    description="Generate structured reports from data",
                    input_types=["data", "template"],
                    output_types=["report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate changelog from git history"""
        import subprocess

        try:
            repo_path = kwargs.get("repo_path", ".")
            since_tag = kwargs.get("since_tag", None)
            max_commits = kwargs.get("max_commits", 100)

            # Get git commits
            git_cmd = ["git", "-C", repo_path, "log", f"--max-count={max_commits}", "--pretty=format:%h|%s|%an|%ad", "--date=short"]
            if since_tag:
                git_cmd.insert(4, f"{since_tag}..HEAD")

            try:
                result = subprocess.run(git_cmd, capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    raise Exception("Not a git repository or git not available")

                commits_raw = result.stdout.strip()
            except (subprocess.SubprocessError, FileNotFoundError) as git_error:
                # No git means no commit history, so nothing was summarised.
                # The template is attached, not passed off as a changelog.
                return ToolResult(
                    success=False,
                    error=f"git history unavailable ({git_error}); template attached",
                    output={
                        "content": self._generate_changelog_template(),
                        "method": "template",
                        "note": "Git not available - generated template"
                    }
                )

            if not commits_raw:
                return ToolResult(
                    success=True,
                    output={
                        "content": self._generate_changelog_template(),
                        "method": "empty",
                        "note": "No commits found"
                    }
                )

            # Parse commits
            commits = []
            for line in commits_raw.split('\n'):
                if '|' in line:
                    parts = line.split('|')
                    if len(parts) >= 4:
                        commits.append({
                            "hash": parts[0],
                            "message": parts[1],
                            "author": parts[2],
                            "date": parts[3]
                        })

            # Use LLM to categorize and format changelog
            from core.services.unified_llm import get_llm_service

            commits_summary = "\n".join([f"- {c['hash']}: {c['message']}" for c in commits[:50]])

            prompt = f"""Generate a CHANGELOG.md from these git commits:

Commits:
{commits_summary}

Requirements:
- Use Keep a Changelog format (https://keepachangelog.com)
- Categorize into: Added, Changed, Deprecated, Removed, Fixed, Security
- Group related commits
- Use proper markdown formatting
- Include commit hashes in parentheses
- Start with ## [Unreleased] section
- Be concise but informative

Return only the CHANGELOG.md content."""

            llm = get_llm_service()
            response = await llm.generate(prompt, max_tokens=2048, temperature=0.3)
            changelog_content = response.get('content', '').strip()

            # Add header if missing
            if not changelog_content.startswith('# Changelog'):
                changelog_content = f"""# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

{changelog_content}"""

            return ToolResult(
                success=True,
                output={
                    "content": changelog_content,
                    "commits_analyzed": len(commits),
                    "method": "llm"
                }
            )

        except Exception as e:
            logger.error(f"Failed to generate changelog: {e}")
            return ToolResult(
                success=False,
                error=f"changelog generation failed ({e}); template attached",
                output={
                    "content": self._generate_changelog_template(),
                    "method": "fallback",
                    "error": str(e)
                }
            )

    def _generate_changelog_template(self) -> str:
        """Generate changelog template"""
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        return f"""# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- New features and functionality

### Changed
- Updates to existing features

### Deprecated
- Features that will be removed in future versions

### Removed
- Removed features

### Fixed
- Bug fixes

### Security
- Security improvements

## [1.0.0] - {today}

### Added
- Initial release
"""


class CreateDiagramTool(Tool):
    """Production-ready diagram generation using LLM for Mermaid syntax"""

    def __init__(self):
        super().__init__()
        self.name = "create_diagram"
        self.description = "Create technical diagrams using Mermaid syntax with LLM assistance"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="diagram_type",
                type="string",
                description="Type of diagram",
                required=True,
                enum=["flowchart", "sequence", "class", "er", "state", "gantt", "architecture"]
            ),
            ToolParameter(
                name="description",
                type="string",
                description="Description of what the diagram should show",
                required=True
            ),
            ToolParameter(
                name="elements",
                type="array",
                description="Key elements/components to include (optional)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="create_diagram",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="CreateDiagram capability"
                ),
                CapabilityMetadata(
                    capability=Capability.CREATE_DIAGRAM,
                    description="Create diagrams from specifications",
                    input_types=["spec", "format"],
                    output_types=["diagram"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate diagram using LLM"""
        try:
            from core.services.unified_llm import get_llm_service

            diagram_type = kwargs.get("diagram_type", "flowchart")
            description = kwargs.get("description", "")
            elements = kwargs.get("elements", [])

            elements_str = ", ".join(elements) if elements else "infer from description"

            # Map diagram types to Mermaid syntax
            mermaid_types = {
                "flowchart": "graph TD",
                "sequence": "sequenceDiagram",
                "class": "classDiagram",
                "er": "erDiagram",
                "state": "stateDiagram-v2",
                "gantt": "gantt",
                "architecture": "graph LR"
            }

            prompt = f"""Generate a Mermaid diagram for the following:

Diagram Type: {diagram_type}
Description: {description}
Key Elements: {elements_str}

Requirements:
- Use proper Mermaid {mermaid_types.get(diagram_type, 'graph')} syntax
- Include all key components and relationships
- Use meaningful labels and IDs
- Follow Mermaid best practices
- Make it clear and professional

Return ONLY the Mermaid diagram code, no explanations, no markdown code fences."""

            llm = get_llm_service()
            response = await llm.generate(prompt, max_tokens=1536, temperature=0.3)
            diagram_code = response.get('content', '').strip()

            # Clean up if LLM wrapped in code fences
            if '```mermaid' in diagram_code:
                diagram_code = diagram_code.split('```mermaid')[1].split('```')[0].strip()
            elif '```' in diagram_code:
                parts = diagram_code.split('```')
                if len(parts) >= 3:
                    diagram_code = parts[1].strip()

            # Wrap in mermaid code fence for rendering
            diagram_markdown = f"""```mermaid
{diagram_code}
```"""

            return ToolResult(
                success=True,
                output={
                    "diagram": diagram_markdown,
                    "diagram_code": diagram_code,
                    "format": "mermaid",
                    "diagram_type": diagram_type
                }
            )

        except Exception as e:
            logger.error(f"Failed to create diagram: {e}")
            # Fallback to simple diagram
            fallback = self._generate_fallback_diagram(
                kwargs.get("diagram_type", "flowchart"),
                kwargs.get("description", "Process")
            )
            return ToolResult(
                success=False,
                error=f"diagram generation failed ({e}); generic shape attached",
                output={
                    "diagram": fallback,
                    "format": "mermaid",
                    "method": "fallback"
                }
            )

    def _generate_fallback_diagram(self, diagram_type: str, description: str) -> str:
        """Generate fallback diagram"""
        if diagram_type == "sequence":
            return f"""```mermaid
sequenceDiagram
    participant A as User
    participant B as System
    A->>B: Request
    B->>A: Response
```"""
        elif diagram_type == "class":
            return f"""```mermaid
classDiagram
    class Component {{
        +property
        +method()
    }}
```"""
        else:
            return f"""```mermaid
graph TD
    A[Start] --> B[{description}]
    B --> C[Process]
    C --> D[End]
```"""


class UpdateDocsTool(Tool):
    """Production-ready documentation update with intelligent merging"""

    def __init__(self):
        super().__init__()
        self.name = "update_docs"
        self.description = "Update existing documentation files with intelligent content merging"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="doc_path",
                type="string",
                description="Path to documentation file to update",
                required=True
            ),
            ToolParameter(
                name="section",
                type="string",
                description="Section to update (e.g., 'Installation', 'API Reference')",
                required=True
            ),
            ToolParameter(
                name="new_content",
                type="string",
                description="New content for the section",
                required=True
            ),
            ToolParameter(
                name="merge_strategy",
                type="string",
                description="How to merge content",
                required=False,
                default="replace",
                enum=["replace", "append", "prepend", "smart_merge"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="update_docs",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="UpdateDocs capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Update documentation section"""
        try:
            doc_path = kwargs.get("doc_path", "")
            section = kwargs.get("section", "")
            new_content = kwargs.get("new_content", "")
            merge_strategy = kwargs.get("merge_strategy", "replace")

            path = Path(doc_path)
            if not path.exists():
                return ToolResult(success=False, output=None, error=f"Documentation file not found: {doc_path}")

            # Read existing content
            with open(path, 'r', encoding='utf-8') as f:
                existing_content = f.read()

            # Find section in markdown
            section_pattern = rf'(##\s+{re.escape(section)}.*?)(?=\n##\s+|\Z)'
            section_match = re.search(section_pattern, existing_content, re.DOTALL)

            if merge_strategy == "replace" and section_match:
                # Replace entire section
                updated_content = re.sub(
                    section_pattern,
                    f"## {section}\n\n{new_content}\n",
                    existing_content,
                    flags=re.DOTALL
                )
            elif merge_strategy == "append" and section_match:
                # Append to section
                section_content = section_match.group(0)
                updated_section = section_content.rstrip() + "\n\n" + new_content + "\n"
                updated_content = existing_content.replace(section_content, updated_section)
            elif merge_strategy == "prepend" and section_match:
                # Prepend to section
                updated_section = f"## {section}\n\n{new_content}\n\n{section_match.group(0)[len(section)+3:]}"
                updated_content = existing_content.replace(section_match.group(0), updated_section)
            else:
                # Section doesn't exist or smart_merge - append new section
                updated_content = existing_content.rstrip() + f"\n\n## {section}\n\n{new_content}\n"

            # Write updated content
            with open(path, 'w', encoding='utf-8') as f:
                f.write(updated_content)

            return ToolResult(
                success=True,
                output={
                    "updated": True,
                    "path": str(path),
                    "section": section,
                    "merge_strategy": merge_strategy,
                    "content_length": len(updated_content)
                }
            )

        except Exception as e:
            logger.error(f"Failed to update docs: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class DocsBuildPreviewTool(Tool):
    """Production-ready documentation build and preview"""

    def __init__(self):
        super().__init__()
        self.name = "docs_build_preview"
        self.description = "Build and preview documentation site using MkDocs or Sphinx"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="docs_dir",
                type="string",
                description="Documentation directory",
                required=False,
                default="docs"
            ),
            ToolParameter(
                name="tool",
                type="string",
                description="Documentation tool to use",
                required=False,
                default="auto",
                enum=["auto", "mkdocs", "sphinx"]
            ),
            ToolParameter(
                name="port",
                type="number",
                description="Preview server port",
                required=False,
                default=8000
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="docs_build_preview",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="DocsBuildPreview capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Build and serve documentation preview"""
        import subprocess

        try:
            docs_dir = kwargs.get("docs_dir", "docs")
            tool = kwargs.get("tool", "auto")
            port = kwargs.get("port", 8000)

            docs_path = Path(docs_dir)
            if not docs_path.exists():
                return ToolResult(success=False, output=None, error=f"Documentation directory not found: {docs_dir}")

            # Auto-detect documentation tool
            if tool == "auto":
                if (docs_path.parent / "mkdocs.yml").exists():
                    tool = "mkdocs"
                elif (docs_path.parent / "conf.py").exists() or (docs_path / "conf.py").exists():
                    tool = "sphinx"
                else:
                    tool = "mkdocs"  # Default

            if tool == "mkdocs":
                # Try to build with MkDocs
                try:
                    # Build docs
                    build_result = subprocess.run(
                        ["mkdocs", "build"],
                        cwd=docs_path.parent,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )

                    if build_result.returncode == 0:
                        return ToolResult(
                            success=True,
                            output={
                                "build_status": "success",
                                "tool": "mkdocs",
                                "output_dir": "site",
                                "preview_command": f"mkdocs serve -a localhost:{port}",
                                "preview_url": f"http://localhost:{port}",
                                "note": f"Run 'mkdocs serve' to preview locally"
                            }
                        )
                    else:
                        return ToolResult(
                            success=False,
                            error=f"MkDocs build failed: {build_result.stderr}"
                        )

                except FileNotFoundError:
                    return ToolResult(
                        success=False,
                        error="MkDocs not installed. Install with: pip install mkdocs"
                    )

            elif tool == "sphinx":
                # Try to build with Sphinx
                try:
                    build_result = subprocess.run(
                        ["sphinx-build", "-b", "html", docs_dir, f"{docs_dir}/_build/html"],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )

                    if build_result.returncode == 0:
                        return ToolResult(
                            success=True,
                            output={
                                "build_status": "success",
                                "tool": "sphinx",
                                "output_dir": f"{docs_dir}/_build/html",
                                "preview_command": f"python -m http.server {port} -d {docs_dir}/_build/html",
                                "preview_url": f"http://localhost:{port}",
                                "note": "Built successfully. Use http.server or sphinx-autobuild to preview"
                            }
                        )
                    else:
                        return ToolResult(
                            success=False,
                            error=f"Sphinx build failed: {build_result.stderr}"
                        )

                except FileNotFoundError:
                    return ToolResult(
                        success=False,
                        error="Sphinx not installed. Install with: pip install sphinx"
                    )

        except Exception as e:
            logger.error(f"Failed to build/preview docs: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class VersionedDocDeploymentTool(Tool):
    """Production-ready versioned documentation deployment"""

    def __init__(self):
        super().__init__()
        self.name = "versioned_doc_deployment"
        self.description = "Deploy versioned documentation with mike or manual versioning"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="version",
                type="string",
                description="Documentation version (e.g., '1.0', 'latest')",
                required=True
            ),
            ToolParameter(
                name="docs_dir",
                type="string",
                description="Documentation directory",
                required=False,
                default="docs"
            ),
            ToolParameter(
                name="alias",
                type="string",
                description="Version alias (e.g., 'stable', 'latest')",
                required=False
            ),
            ToolParameter(
                name="push",
                type="boolean",
                description="Push to gh-pages branch",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="versioned_doc_deployment",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="VersionedDocDeployment capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Deploy versioned documentation"""
        import subprocess

        try:
            version = kwargs.get("version", "latest")
            docs_dir = kwargs.get("docs_dir", "docs")
            alias = kwargs.get("alias", None)
            push = kwargs.get("push", False)

            # Check if mike is available (for MkDocs versioning)
            try:
                mike_cmd = ["mike", "deploy", "--update-aliases", version]
                if alias:
                    mike_cmd.append(alias)
                if push:
                    mike_cmd.append("--push")

                result = subprocess.run(
                    mike_cmd,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if result.returncode == 0:
                    return ToolResult(
                        success=True,
                        output={
                            "deployed": True,
                            "version": version,
                            "alias": alias,
                            "method": "mike",
                            "pushed_to_remote": push,
                            "url": f"https://<username>.github.io/<repo>/{version}/",
                            "note": "Deployed with mike. Update URL with your GitHub Pages domain."
                        }
                    )
                else:
                    raise Exception(f"Mike deployment failed: {result.stderr}")

            except FileNotFoundError:
                # NOTHING WAS DEPLOYED. `deployed: False` was in the output but
                # success=True is what a caller branches on.
                return ToolResult(
                    success=False,
                    error="mike is not installed, so nothing was deployed; "
                          "manual instructions attached",
                    output={
                        "deployed": False,
                        "version": version,
                        "method": "manual",
                        "instructions": [
                            "1. Install mike: pip install mike",
                            f"2. Deploy version: mike deploy --push {version} {alias or ''}",
                            "3. Set default: mike set-default latest",
                            "4. Configure GitHub Pages to serve from gh-pages branch"
                        ],
                        "note": "Mike not installed. Follow manual instructions above."
                    }
                )

        except Exception as e:
            logger.error(f"Failed to deploy versioned docs: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                output={
                    "deployed": False,
                    "version": version,
                    "error_details": str(e)
                }
            )


class ADRGeneratorTool(Tool):
    """Generate Architecture Decision Records (ADR)"""

    def __init__(self):
        super().__init__()
        self.name = "adr_generator"
        self.description = "Generate Architecture Decision Records"
        self.parameters = [
            ToolParameter(
                name="decision_title",
                type="string",
                description="Title of the architecture decision",
                required=True
            ),
            ToolParameter(
                name="context",
                type="string",
                description="Context for the decision",
                required=True
            ),
            ToolParameter(
                name="decision",
                type="string",
                description="The decision made",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="adr_generator",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="ADRGenerator capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate ADR"""
        try:
            title = kwargs.get("decision_title", "")
            context = kwargs.get("context", "")
            decision = kwargs.get("decision", "")

            from datetime import datetime
            date = datetime.now().strftime("%Y-%m-%d")

            adr = f"""# {title}

Date: {date}

## Status

Accepted

## Context

{context}

## Decision

{decision}

## Consequences

TBD
"""

            return ToolResult(success=True, output={"adr": adr, "title": title})
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


# ============================================================================
# REAL DOCUMENT GENERATION TOOLS (PDF, DOCX, PPTX, etc.)
# ============================================================================


class GeneratePDFDocumentTool(Tool):
    """Generate actual PDF documents using reportlab"""

    def __init__(self):
        super().__init__()
        self.name = "generate_pdf_document"
        self.description = "Generate a real PDF document with formatting, images, and styling"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="output_path",
                type="string",
                description="Path where PDF should be saved",
                required=True
            ),
            ToolParameter(
                name="title",
                type="string",
                description="Document title",
                required=True
            ),
            ToolParameter(
                name="content",
                type="string",
                description="Document content (supports markdown-like formatting)",
                required=True
            ),
            ToolParameter(
                name="author",
                type="string",
                description="Document author",
                required=False
            ),
            ToolParameter(
                name="include_toc",
                type="boolean",
                description="Include table of contents",
                required=False,
                default=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_pdf_document",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="GeneratePDFDocument capability"
                )
            ]
        )

    def _to_roman(self, num):
        """Convert integer to Roman numeral"""
        val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
        syms = ['M', 'CM', 'D', 'CD', 'C', 'XC', 'L', 'XL', 'X', 'IX', 'V', 'IV', 'I']
        roman_num = ''
        i = 0
        while num > 0:
            for _ in range(num // val[i]):
                roman_num += syms[i]
                num -= val[i]
            i += 1
        return roman_num

    async def execute(self, **kwargs) -> ToolResult:
        """Generate enterprise-grade PDF document with professional styling"""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
            from datetime import datetime

            output_path = kwargs.get("output_path")
            title = kwargs.get("title", "Document")
            content = kwargs.get("content", "")
            author = kwargs.get("author", "TorinAI")
            include_toc = kwargs.get("include_toc", False)

            # Create PDF with professional margins
            doc = SimpleDocTemplate(
                output_path,
                pagesize=letter,
                rightMargin=0.75*inch,
                leftMargin=0.75*inch,
                topMargin=1*inch,
                bottomMargin=0.75*inch,
                title=title,
                author=author
            )
            story = []
            styles = getSampleStyleSheet()

            # Corporate color scheme
            primary_color = colors.HexColor('#1a1a2e')
            secondary_color = colors.HexColor('#16213e')
            text_color = colors.HexColor('#2C3E50')
            accent_color = colors.HexColor('#3498DB')

            # Professional title style (cover page)
            cover_title_style = ParagraphStyle(
                'CoverTitle',
                parent=styles['Title'],
                fontSize=32,
                textColor=primary_color,
                spaceAfter=0.4*inch,
                alignment=TA_CENTER,
                fontName='Helvetica-Bold',
                leading=38
            )

            # Cover page layout
            story.append(Spacer(1, 2*inch))
            story.append(Paragraph(title, cover_title_style))

            # Metadata on cover
            meta_style = ParagraphStyle(
                'Metadata',
                parent=styles['Normal'],
                fontSize=12,
                textColor=secondary_color,
                spaceAfter=6,
                alignment=TA_CENTER,
                fontName='Helvetica'
            )
            story.append(Paragraph(f"<b>Author:</b> {author}", meta_style))
            story.append(Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%B %d, %Y at %H:%M')}", meta_style))
            story.append(PageBreak())

            # Professional heading styles
            h1_style = ParagraphStyle(
                'EnterpriseH1',
                parent=styles['Heading1'],
                fontSize=20,
                textColor=primary_color,
                spaceBefore=0.3*inch,
                spaceAfter=0.12*inch,
                fontName='Helvetica-Bold',
                leading=22,
                borderColor=accent_color,
                borderWidth=0,
                borderPadding=6
            )

            h2_style = ParagraphStyle(
                'EnterpriseH2',
                parent=styles['Heading2'],
                fontSize=12,
                textColor=secondary_color,
                spaceBefore=0.2*inch,
                spaceAfter=0.08*inch,
                fontName='Helvetica-Bold',
                leading=12
            )

            h3_style = ParagraphStyle(
                'EnterpriseH3',
                parent=styles['Heading3'],
                fontSize=12,
                textColor=secondary_color,
                spaceBefore=0.15*inch,
                spaceAfter=0.06*inch,
                fontName='Helvetica-Bold',
                leading=13
            )

            # Professional body text
            body_style = ParagraphStyle(
                'EnterpriseBody',
                parent=styles['Normal'],
                fontSize=12,
                leading=16,
                spaceBefore=4,
                spaceAfter=8,
                textColor=text_color,
                alignment=TA_LEFT,
                fontName='Helvetica'
            )

            # Bullet point style
            bullet_style = ParagraphStyle(
                'EnterpriseBullet',
                parent=body_style,
                leftIndent=25,
                bulletIndent=10,
                spaceBefore=6,
                spaceAfter=6,
                alignment=TA_LEFT
            )

            # Pre-process content: split headers from their content
            # This ensures "## Header\n- bullet" becomes two separate paragraphs
            preprocessed_content = content
            # Add double newline after headers if followed by single newline
            preprocessed_content = re.sub(r'^(#{1,3}\s+[^\n]+)\n([^#\n])', r'\1\n\n\2', preprocessed_content, flags=re.MULTILINE)

            # Process content with intelligent parsing
            paragraphs = preprocessed_content.split('\n\n')
            section_number = 0
            last_para_type = None  # Track previous paragraph type

            for i, para in enumerate(paragraphs):
                if not para.strip():
                    continue

                # Explicit markdown headers
                if para.startswith('# '):
                    section_number += 1
                    roman = self._to_roman(section_number)
                    story.append(Paragraph(f"{roman}. {para[2:].strip()}", h1_style))
                    last_para_type = 'h1'

                elif para.startswith('## '):
                    # h2 style already has appropriate spaceBefore - no extra spacing needed
                    story.append(Paragraph(para[3:].strip(), h2_style))
                    last_para_type = 'h2'

                elif para.startswith('### '):
                    story.append(Paragraph(para[4:].strip(), h3_style))
                    last_para_type = 'h3'

                # Bullet lists
                elif para.strip().startswith(('- ', '• ', '* ')):
                    bullet_lines = para.strip().split('\n')
                    for bullet in bullet_lines:
                        bullet_stripped = bullet.strip()
                        if bullet_stripped.startswith('- '):
                            clean_bullet = bullet_stripped[2:].strip()
                        elif bullet_stripped.startswith('• '):
                            clean_bullet = bullet_stripped[2:].strip()
                        elif bullet_stripped.startswith('* '):
                            clean_bullet = bullet_stripped[2:].strip()
                        else:
                            continue

                        if clean_bullet:
                            # Handle markdown formatting - bold, italic, code
                            clean_bullet = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', clean_bullet)  # Bold (non-greedy)
                            clean_bullet = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', clean_bullet)  # Italic
                            clean_bullet = re.sub(r'`([^`]+)`', r'<font name="Courier">\1</font>', clean_bullet)  # Code
                            story.append(Paragraph(f"• {clean_bullet}", bullet_style))
                    story.append(Spacer(1, 0.15*inch))
                    last_para_type = 'bullets'

                # Numbered lists
                elif re.match(r'^\d+\.', para.strip()):
                    items = para.strip().split('\n')
                    for item in items:
                        if item.strip():
                            story.append(Paragraph(item.strip(), bullet_style))
                    story.append(Spacer(1, 0.1*inch))
                    last_para_type = 'numbered'

                # Regular paragraphs (check for inline bullets)
                else:
                    # Check if this paragraph has inline bullet lists like "text: - item1 - item2"
                    if re.search(r':\s*-\s+\*\*', para):
                        # Split intro text from bullets
                        parts = re.split(r'(:\s*-\s+)', para, maxsplit=1)
                        if len(parts) >= 2:
                            # Add intro text
                            intro = parts[0] + ':'
                            intro = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', intro)
                            intro = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', intro)
                            story.append(Paragraph(intro, body_style))
                            story.append(Spacer(1, 0.1*inch))

                            # Process remaining text as bullets
                            bullet_text = parts[2] if len(parts) > 2 else ""
                            # Split by " - " pattern
                            bullets = re.split(r'\s+-\s+', bullet_text)
                            for bullet in bullets:
                                if bullet.strip():
                                    clean = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', bullet.strip())
                                    clean = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', clean)
                                    story.append(Paragraph(f"• {clean}", bullet_style))
                            story.append(Spacer(1, 0.1*inch))
                            last_para_type = 'bullets'
                            continue

                    # Regular paragraph without inline bullets
                    processed = para.strip()
                    processed = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', processed)  # Bold (non-greedy)
                    processed = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', processed)  # Italic
                    processed = re.sub(r'`([^`]+)`', r'<font name="Courier">\1</font>', processed)  # Code

                    story.append(Paragraph(processed, body_style))
                    last_para_type = 'paragraph'

            # Add professional footer with page numbers
            def add_page_footer(canvas_obj, doc_obj):
                """Add footer with page numbers"""
                canvas_obj.saveState()
                canvas_obj.setFont('Helvetica', 9)
                canvas_obj.setFillColor(colors.HexColor('#666666'))

                # Page number
                page_num = f"Page {canvas_obj.getPageNumber()}"
                canvas_obj.drawRightString(
                    letter[0] - 0.75*inch,
                    0.5*inch,
                    page_num
                )

                # Footer text
                canvas_obj.drawString(
                    0.75*inch,
                    0.5*inch,
                    f"{author} • {title}"
                )

                canvas_obj.restoreState()

            # Build PDF
            doc.build(story, onFirstPage=add_page_footer, onLaterPages=add_page_footer)

            return ToolResult(
                success=True,
                output={
                    "pdf_path": output_path,
                    "title": title,
                    "pages": "generated",
                    "format": "PDF",
                    "size_bytes": Path(output_path).stat().st_size if Path(output_path).exists() else 0
                }
            )

        except Exception as e:
            logger.error(f"Failed to generate PDF: {e}")
            import traceback
            traceback.print_exc()
            return ToolResult(success=False, output=None, error=str(e))


class GenerateWordDocumentTool(Tool):
    """Generate Microsoft Word .docx documents"""

    def __init__(self):
        super().__init__()
        self.name = "generate_word_document"
        self.description = "Generate a Microsoft Word .docx document with formatting"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="output_path",
                type="string",
                description="Path where .docx should be saved",
                required=True
            ),
            ToolParameter(
                name="title",
                type="string",
                description="Document title",
                required=True
            ),
            ToolParameter(
                name="content",
                type="string",
                description="Document content",
                required=True
            ),
            ToolParameter(
                name="author",
                type="string",
                description="Document author",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_word_document",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="GenerateWordDocument capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate Word document"""
        try:
            from docx import Document
            from docx.shared import Inches, Pt, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH

            output_path = kwargs.get("output_path")
            title = kwargs.get("title", "Document")
            content = kwargs.get("content", "")
            author = kwargs.get("author", "TorinAI")

            # Create document
            doc = Document()

            # Set document properties
            doc.core_properties.title = title
            doc.core_properties.author = author

            # Add title
            title_para = doc.add_heading(title, 0)
            title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

            # Add metadata
            doc.add_paragraph(f"Author: {author}")
            from datetime import datetime
            doc.add_paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            doc.add_paragraph()

            # Process content
            paragraphs = content.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    # Check for headers
                    if para.startswith('# '):
                        doc.add_heading(para[2:], level=1)
                    elif para.startswith('## '):
                        doc.add_heading(para[3:], level=2)
                    elif para.startswith('### '):
                        doc.add_heading(para[4:], level=3)
                    else:
                        doc.add_paragraph(para)

            # Save document
            doc.save(output_path)

            return ToolResult(
                success=True,
                output={
                    "docx_path": output_path,
                    "title": title,
                    "format": "DOCX",
                    "size_bytes": Path(output_path).stat().st_size if Path(output_path).exists() else 0
                }
            )

        except Exception as e:
            logger.error(f"Failed to generate Word document: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class GeneratePowerPointTool(Tool):
    """Generate PowerPoint .pptx presentations"""

    def __init__(self):
        super().__init__()
        self.name = "generate_powerpoint"
        self.description = "Generate a PowerPoint .pptx presentation with slides"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="output_path",
                type="string",
                description="Path where .pptx should be saved",
                required=True
            ),
            ToolParameter(
                name="title",
                type="string",
                description="Presentation title",
                required=True
            ),
            ToolParameter(
                name="slides",
                type="array",
                description="List of slides with 'title' and 'content' keys",
                required=True
            ),
            ToolParameter(
                name="author",
                type="string",
                description="Presentation author",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_powerpoint",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="GeneratePowerPoint capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate PowerPoint presentation"""
        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt

            output_path = kwargs.get("output_path")
            title = kwargs.get("title", "Presentation")
            slides_data = kwargs.get("slides", [])
            author = kwargs.get("author", "TorinAI")

            # Create presentation
            prs = Presentation()
            prs.core_properties.title = title
            prs.core_properties.author = author

            # Add title slide
            title_slide_layout = prs.slide_layouts[0]
            slide = prs.slides.add_slide(title_slide_layout)
            slide_title = slide.shapes.title
            subtitle = slide.placeholders[1]
            slide_title.text = title
            from datetime import datetime
            subtitle.text = f"By {author} | {datetime.now().strftime('%Y-%m-%d')}"

            # Add content slides
            for slide_data in slides_data:
                if isinstance(slide_data, dict):
                    bullet_slide_layout = prs.slide_layouts[1]
                    slide = prs.slides.add_slide(bullet_slide_layout)
                    shapes = slide.shapes

                    title_shape = shapes.title
                    body_shape = shapes.placeholders[1]

                    title_shape.text = slide_data.get('title', 'Slide')

                    text_frame = body_shape.text_frame
                    content = slide_data.get('content', '')

                    # Split content into bullet points
                    bullets = content.split('\n')
                    for i, bullet in enumerate(bullets):
                        if bullet.strip():
                            if i == 0:
                                text_frame.text = bullet.strip()
                            else:
                                p = text_frame.add_paragraph()
                                p.text = bullet.strip()
                                p.level = 0

            # Save presentation
            prs.save(output_path)

            return ToolResult(
                success=True,
                output={
                    "pptx_path": output_path,
                    "title": title,
                    "slide_count": len(prs.slides),
                    "format": "PPTX",
                    "size_bytes": Path(output_path).stat().st_size if Path(output_path).exists() else 0
                }
            )

        except Exception as e:
            logger.error(f"Failed to generate PowerPoint: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class GenerateArchitectureDiagramTool(Tool):
    """Generate architecture diagrams as PNG/SVG images"""

    def __init__(self):
        super().__init__()
        self.name = "generate_architecture_diagram"
        self.description = "Generate system architecture diagram as PNG or SVG image"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="output_path",
                type="string",
                description="Path where diagram image should be saved (.png or .svg)",
                required=True
            ),
            ToolParameter(
                name="components",
                type="array",
                description="List of system components to include",
                required=True
            ),
            ToolParameter(
                name="title",
                type="string",
                description="Diagram title",
                required=False
            ),
            ToolParameter(
                name="style",
                type="string",
                description="Diagram style (layered, circular, hierarchical)",
                required=False,
                default="layered"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_architecture_diagram",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="GenerateArchitectureDiagram capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate enterprise-grade architecture diagram with professional styling"""
        try:
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches
            from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle
            import numpy as np

            output_path = kwargs.get("output_path")
            components = kwargs.get("components", [])
            title = kwargs.get("title", "System Architecture")
            style = kwargs.get("style", "layered")

            # Create large, high-quality figure
            fig, ax = plt.subplots(figsize=(16, 12), facecolor='white', dpi=150)
            ax.set_xlim(0, 16)
            ax.set_ylim(0, 12)
            ax.axis('off')

            # Professional title with large font
            ax.text(8, 11.2, title, ha='center', va='top',
                   fontsize=24, fontweight='bold', color='#1a1a2e',
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='#f0f0f0', edgecolor='#1a1a2e', linewidth=2))

            # Corporate color palette
            colors_palette = ['#3498DB', '#2ECC71', '#F39C12', '#E74C3C', '#9B59B6', '#1ABC9C']

            if style == "layered":
                # Layered architecture with generous spacing
                num_components = len(components) if components else 4
                if not components:
                    components = ["Presentation Layer", "Business Logic Layer", "Data Access Layer", "Database Layer"]

                # Calculate positions with generous spacing (minimum 1.5 units between components)
                available_height = 8.5  # From y=10 down to y=1.5
                spacing = min(available_height / max(num_components - 1, 1), 2.0)  # Max 2.0 spacing
                y_start = 10

                for i, comp in enumerate(components):
                    y_pos = y_start - (i * spacing)
                    comp_name = comp if isinstance(comp, str) else comp.get('name', f'Component {i+1}')
                    comp_color = colors_palette[i % len(colors_palette)]

                    # Large component box with rounded corners
                    box = FancyBboxPatch(
                        (2.5, y_pos - 0.5),  # x, y with generous height
                        11, 1.0,  # width, height (taller boxes)
                        boxstyle="round,pad=0.2",
                        edgecolor='#1a1a2e',
                        facecolor=comp_color,
                        linewidth=3,
                        alpha=0.9
                    )
                    ax.add_patch(box)

                    # Large, clear text
                    ax.text(8, y_pos, comp_name, ha='center', va='center',
                           fontsize=16, color='white', fontweight='bold',
                           bbox=dict(boxstyle='round,pad=0.3', facecolor=comp_color,
                                   edgecolor='none', alpha=0.0))

                    # Professional arrows between layers with generous spacing
                    if i < len(components) - 1:
                        arrow_start_y = y_pos - 0.6
                        arrow_end_y = y_pos - spacing + 0.6

                        arrow = FancyArrowPatch(
                            (8, arrow_start_y),
                            (8, arrow_end_y),
                            arrowstyle='->,head_width=0.6,head_length=0.6',
                            mutation_scale=40,
                            color='#2C3E50',
                            linewidth=4,
                            zorder=1
                        )
                        ax.add_patch(arrow)

            elif style == "circular" or style == "network":
                # Circular/network layout with nodes
                num_components = len(components) if components else 6
                if not components:
                    components = ["API Gateway", "Service A", "Service B", "Database", "Cache", "Queue"]

                # Arrange in circle with generous radius
                radius = 3.5
                center_x, center_y = 8, 6

                positions = []
                for i in range(num_components):
                    angle = 2 * np.pi * i / num_components - np.pi / 2
                    x = center_x + radius * np.cos(angle)
                    y = center_y + radius * np.sin(angle)
                    positions.append((x, y))

                    comp_name = components[i] if isinstance(components[i], str) else components[i].get('name', f'Node {i+1}')
                    comp_color = colors_palette[i % len(colors_palette)]

                    # Large circular nodes
                    circle = Circle(
                        (x, y), 0.8,
                        edgecolor='#1a1a2e',
                        facecolor=comp_color,
                        linewidth=3,
                        alpha=0.9,
                        zorder=2
                    )
                    ax.add_patch(circle)

                    # Node label with clear text
                    ax.text(x, y, comp_name, ha='center', va='center',
                           fontsize=14, color='white', fontweight='bold',
                           zorder=3)

                # Draw connections between nodes
                for i in range(num_components):
                    next_i = (i + 1) % num_components
                    arrow = FancyArrowPatch(
                        positions[i],
                        positions[next_i],
                        arrowstyle='<->,head_width=0.4,head_length=0.4',
                        mutation_scale=25,
                        color='#95A5A6',
                        linewidth=2.5,
                        alpha=0.6,
                        zorder=1
                    )
                    ax.add_patch(arrow)

            else:  # hierarchical or default
                # Hierarchical tree layout
                num_components = len(components) if components else 5
                if not components:
                    components = ["Root System", "Module A", "Module B", "Subsystem 1", "Subsystem 2"]

                # Simple hierarchical layout
                y_positions = np.linspace(10, 2, min(num_components, 4))

                for i, comp in enumerate(components[:4]):
                    y_pos = y_positions[i]
                    comp_name = comp if isinstance(comp, str) else comp.get('name', f'Component {i+1}')
                    comp_color = colors_palette[i % len(colors_palette)]

                    box = FancyBboxPatch(
                        (5, y_pos - 0.5),
                        6, 1.0,
                        boxstyle="round,pad=0.2",
                        edgecolor='#1a1a2e',
                        facecolor=comp_color,
                        linewidth=3,
                        alpha=0.9
                    )
                    ax.add_patch(box)

                    ax.text(8, y_pos, comp_name, ha='center', va='center',
                           fontsize=16, color='white', fontweight='bold')

            # Add professional border
            border = mpatches.Rectangle(
                (0.2, 0.2), 15.6, 11.6,
                linewidth=3, edgecolor='#1a1a2e',
                facecolor='none', linestyle='-', alpha=0.3
            )
            ax.add_patch(border)

            # Save with ultra-high quality
            plt.tight_layout(pad=1.5)
            plt.savefig(output_path, dpi=300, bbox_inches='tight',
                       facecolor='white', edgecolor='none', pad_inches=0.5)
            plt.close()

            return ToolResult(
                success=True,
                output={
                    "diagram_path": output_path,
                    "title": title,
                    "component_count": len(components),
                    "format": "PNG" if output_path.endswith('.png') else "SVG",
                    "size_bytes": Path(output_path).stat().st_size if Path(output_path).exists() else 0
                }
            )

        except Exception as e:
            logger.error(f"Failed to generate architecture diagram: {e}")
            import traceback
            traceback.print_exc()
            return ToolResult(success=False, output=None, error=str(e))


class CreateFlowchartTool(Tool):
    """Generate flowchart diagrams as images"""

    def __init__(self):
        super().__init__()
        self.name = "create_flowchart"
        self.description = "Create flowchart diagram as PNG image with shapes and connections"
        self.category = ToolCategory.DOCUMENTATION
        self.parameters = [
            ToolParameter(
                name="output_path",
                type="string",
                description="Path where flowchart should be saved",
                required=True
            ),
            ToolParameter(
                name="steps",
                type="array",
                description="List of flowchart steps with 'type' (start, process, decision, end) and 'text'",
                required=True
            ),
            ToolParameter(
                name="title",
                type="string",
                description="Flowchart title",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="create_flowchart",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOCUMENT_CODE,
                    description="CreateFlowchart capability"
                )
            ]
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate flowchart"""
        try:
            import matplotlib.pyplot as plt
            from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Polygon, Ellipse
            import numpy as np

            output_path = kwargs.get("output_path")
            steps = kwargs.get("steps", [])
            title = kwargs.get("title", "Flowchart")

            # Create figure
            fig, ax = plt.subplots(figsize=(10, 12))
            ax.set_xlim(0, 10)
            ax.set_ylim(0, len(steps) * 1.5 + 2)
            ax.axis('off')

            # Add title
            ax.text(5, len(steps) * 1.5 + 1.5, title, ha='center', va='top',
                   fontsize=18, fontweight='bold')

            y_pos = len(steps) * 1.5
            for i, step in enumerate(steps):
                step_type = step.get('type', 'process') if isinstance(step, dict) else 'process'
                step_text = step.get('text', f'Step {i+1}') if isinstance(step, dict) else str(step)

                if step_type == 'start' or step_type == 'end':
                    # Oval shape
                    box = Ellipse(
                        (5, y_pos), 3, 0.6,
                        edgecolor='#27AE60' if step_type == 'start' else '#E74C3C',
                        facecolor='#2ECC71' if step_type == 'start' else '#EC7063',
                        linewidth=2
                    )
                    ax.add_patch(box)
                    ax.text(5, y_pos, step_text, ha='center', va='center',
                           fontsize=10, color='white', fontweight='bold')

                elif step_type == 'decision':
                    # Diamond shape
                    diamond = Polygon(
                        [(5, y_pos + 0.4), (3.5, y_pos), (5, y_pos - 0.4), (6.5, y_pos)],
                        closed=True, edgecolor='#F39C12', facecolor='#F4D03F', linewidth=2
                    )
                    ax.add_patch(diamond)
                    ax.text(5, y_pos, step_text, ha='center', va='center',
                           fontsize=9, color='#34495E', fontweight='bold')

                else:  # process
                    # Rectangle
                    box = FancyBboxPatch(
                        (3.5, y_pos - 0.3), 3, 0.6,
                        boxstyle="round,pad=0.05",
                        edgecolor='#3498DB', facecolor='#5DADE2', linewidth=2
                    )
                    ax.add_patch(box)
                    ax.text(5, y_pos, step_text, ha='center', va='center',
                           fontsize=10, color='white', fontweight='bold')

                # Add arrow to next step
                if i < len(steps) - 1:
                    arrow = FancyArrowPatch(
                        (5, y_pos - 0.45), (5, y_pos - 1.05),
                        arrowstyle='->', mutation_scale=15,
                        color='#34495E', linewidth=1.5
                    )
                    ax.add_patch(arrow)

                y_pos -= 1.5

            # Save
            plt.tight_layout()
            plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
            plt.close()

            return ToolResult(
                success=True,
                output={
                    "flowchart_path": output_path,
                    "step_count": len(steps),
                    "format": "PNG",
                    "size_bytes": Path(output_path).stat().st_size if Path(output_path).exists() else 0
                }
            )

        except Exception as e:
            logger.error(f"Failed to generate flowchart: {e}")
            return ToolResult(success=False, output=None, error=str(e))
