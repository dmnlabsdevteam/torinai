#!/usr/bin/env python3
"""
AI/ML Tools
======================
Tool definitions for AI agents

Purpose:
- Define callable tools for AI agents
- Provide ML/AI capabilities
- Enable agent tool use
- Function calling interface
"""

import asyncio
import logging
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from core.tools.tool_registry import Tool, ToolResult, ToolParameter as RegistryToolParameter
from core.tools.capabilities import (
    ToolCapabilityProfile, CapabilityMetadata, Capability, RiskLevel
)

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """Tool parameter definition"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: List[str] = field(default_factory=list)


@dataclass
class AIToolDefinition:
    """AI Tool definition - NOT the same as Tool base class"""
    name: str
    description: str
    parameters: List[ToolParameter]
    function: Callable
    category: str = "general"
    requires_auth: bool = False


class AIMLTools:
    """
    AI/ML Tools Registry

    Purpose:
    - Register and manage tools for AI agents
    - Provide tool calling interface
    - Execute tool functions safely
    - Track tool usage

    Usage:
        tools = AIMLTools()
        result = await tools.execute_tool("search_web", {"query": "AI news"})
    """

    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self.usage_stats: Dict[str, int] = {}

        # Register default tools
        self._register_default_tools()

        logger.info("AIMLTools initialized")

    def _register_default_tools(self):
        """Register default AI/ML tools"""

        # Web Search Tool
        self.register_tool(Tool(
            name="search_web",
            description="Search the web for information using a query string",
            category="research",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query to find information",
                    required=True
                ),
                ToolParameter(
                    name="num_results",
                    type="integer",
                    description="Number of results to return (1-10)",
                    required=False,
                    default=5
                )
            ],
            function=self._search_web
        ))

        # Code Analysis Tool
        self.register_tool(Tool(
            name="analyze_code",
            description="Analyze code for bugs, security issues, and quality metrics",
            category="development",
            parameters=[
                ToolParameter(
                    name="code",
                    type="string",
                    description="Source code to analyze",
                    required=True
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="Programming language",
                    required=False,
                    default="python",
                    enum=["python", "javascript", "typescript", "java", "go"]
                )
            ],
            function=self._analyze_code
        ))

        # Data Analysis Tool
        self.register_tool(Tool(
            name="analyze_data",
            description="Analyze data and generate statistical insights",
            category="analytics",
            parameters=[
                ToolParameter(
                    name="data",
                    type="object",
                    description="Data to analyze (JSON format)",
                    required=True
                ),
                ToolParameter(
                    name="analysis_type",
                    type="string",
                    description="Type of analysis to perform",
                    required=False,
                    default="summary",
                    enum=["summary", "correlation", "distribution", "trend"]
                )
            ],
            function=self._analyze_data
        ))

        # Text Summarization Tool
        self.register_tool(Tool(
            name="summarize_text",
            description="Summarize long text into concise key points",
            category="nlp",
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to summarize",
                    required=True
                ),
                ToolParameter(
                    name="max_length",
                    type="integer",
                    description="Maximum length of summary in words",
                    required=False,
                    default=100
                )
            ],
            function=self._summarize_text
        ))

        # Sentiment Analysis Tool
        self.register_tool(Tool(
            name="analyze_sentiment",
            description="Analyze sentiment of text (positive, negative, neutral)",
            category="nlp",
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to analyze sentiment",
                    required=True
                )
            ],
            function=self._analyze_sentiment
        ))

        # Image Analysis Tool
        self.register_tool(Tool(
            name="analyze_image",
            description="Analyze image content and extract information",
            category="vision",
            parameters=[
                ToolParameter(
                    name="image_url",
                    type="string",
                    description="URL of image to analyze",
                    required=True
                ),
                ToolParameter(
                    name="analysis_type",
                    type="string",
                    description="Type of analysis",
                    required=False,
                    default="objects",
                    enum=["objects", "text", "faces", "scene"]
                )
            ],
            function=self._analyze_image
        ))

        # Translation Tool
        self.register_tool(Tool(
            name="translate_text",
            description="Translate text from one language to another",
            category="nlp",
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to translate",
                    required=True
                ),
                ToolParameter(
                    name="target_language",
                    type="string",
                    description="Target language code (e.g., 'es', 'fr', 'de')",
                    required=True
                ),
                ToolParameter(
                    name="source_language",
                    type="string",
                    description="Source language code (auto-detect if not specified)",
                    required=False,
                    default="auto"
                )
            ],
            function=self._translate_text
        ))

        # Email Validation Tool
        self.register_tool(Tool(
            name="validate_email",
            description="Validate email address format and deliverability",
            category="validation",
            parameters=[
                ToolParameter(
                    name="email",
                    type="string",
                    description="Email address to validate",
                    required=True
                )
            ],
            function=self._validate_email
        ))

        # URL Validation Tool
        self.register_tool(Tool(
            name="validate_url",
            description="Validate URL format and check if accessible",
            category="validation",
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="URL to validate",
                    required=True
                ),
                ToolParameter(
                    name="check_accessible",
                    type="boolean",
                    description="Check if URL is accessible via HTTP request",
                    required=False,
                    default=False
                )
            ],
            function=self._validate_url
        ))

        # Calculator Tool
        self.register_tool(Tool(
            name="calculate",
            description="Perform mathematical calculations safely",
            category="math",
            parameters=[
                ToolParameter(
                    name="expression",
                    type="string",
                    description="Mathematical expression to evaluate",
                    required=True
                )
            ],
            function=self._calculate
        ))

    def register_tool(self, tool: AIToolDefinition):
        """Register a new tool"""
        self.tools[tool.name] = tool
        self.usage_stats[tool.name] = 0
        logger.info(f"Registered tool: {tool.name}")

    def unregister_tool(self, tool_name: str):
        """Unregister a tool"""
        if tool_name in self.tools:
            del self.tools[tool_name]
            logger.info(f"Unregistered tool: {tool_name}")

    def get_tool(self, tool_name: str) -> Optional[AIToolDefinition]:
        """Get tool by name"""
        return self.tools.get(tool_name)

    def list_tools(self, category: Optional[str] = None) -> List[AIToolDefinition]:
        """List all tools, optionally filtered by category"""
        if category:
            return [t for t in self.tools.values() if t.category == category]
        return list(self.tools.values())

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions in OpenAI function calling format"""
        definitions = []

        for tool in self.tools.values():
            properties = {}
            required = []

            for param in tool.parameters:
                param_def = {
                    "type": param.type,
                    "description": param.description
                }

                if param.enum:
                    param_def["enum"] = param.enum

                properties[param.name] = param_def

                if param.required:
                    required.append(param.name)

            definitions.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            })

        return definitions

    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool with given parameters

        Args:
            tool_name: Name of tool to execute
            parameters: Tool parameters

        Returns:
            Tool execution result
        """
        try:
            tool = self.get_tool(tool_name)

            if not tool:
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' not found"
                }

            # Validate parameters
            validation_error = self._validate_parameters(tool, parameters)
            if validation_error:
                return {
                    "success": False,
                    "error": validation_error
                }

            # Add default values for optional parameters
            for param in tool.parameters:
                if param.name not in parameters and param.default is not None:
                    parameters[param.name] = param.default

            # Execute tool function
            result = await tool.function(**parameters)

            # Track usage
            self.usage_stats[tool_name] += 1

            return {
                "success": True,
                "result": result
            }

        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name} - {e}")
            return {
                "success": False,
                "error": f"Tool execution error: {str(e)}"
            }

    def _validate_parameters(
        self,
        tool: AIToolDefinition,
        parameters: Dict[str, Any]
    ) -> Optional[str]:
        """Validate tool parameters"""

        # Check required parameters
        for param in tool.parameters:
            if param.required and param.name not in parameters:
                return f"Missing required parameter: {param.name}"

            # Check enum values
            if param.enum and param.name in parameters:
                if parameters[param.name] not in param.enum:
                    return f"Invalid value for {param.name}. Must be one of: {param.enum}"

        return None

    # Tool implementations

    async def _search_web(self, query: str, num_results: int = 5) -> Dict[str, Any]:
        """Search the web"""
        logger.info(f"Web search: {query}")

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Use DuckDuckGo Instant Answer API
                url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()

                        results = []

                        # Add abstract if available
                        if data.get('Abstract'):
                            results.append({
                                "title": data.get('Heading', query),
                                "url": data.get('AbstractURL', ''),
                                "snippet": data.get('Abstract', '')
                            })

                        # Add related topics
                        for topic in data.get('RelatedTopics', [])[:num_results]:
                            if isinstance(topic, dict) and 'Text' in topic:
                                results.append({
                                    "title": topic.get('Text', '')[:50],
                                    "url": topic.get('FirstURL', ''),
                                    "snippet": topic.get('Text', '')
                                })

                        return {
                            "query": query,
                            "results": results[:num_results]
                        }
        except Exception as e:
            logger.error(f"Web search error: {e}")

        return {
            "query": query,
            "results": [],
            "error": "Search API unavailable"
        }

    async def _analyze_code(
        self,
        code: str,
        language: str = "python"
    ) -> Dict[str, Any]:
        """Analyze code"""
        logger.info(f"Analyzing {language} code ({len(code)} chars)")

        lines = [l for l in code.split('\n') if l.strip()]
        issues = []

        if language == "python":
            import ast
            try:
                tree = ast.parse(code)
                complexity = 0

                # Calculate complexity
                for node in ast.walk(tree):
                    if isinstance(node, (ast.If, ast.For, ast.While, ast.FunctionDef, ast.AsyncFunctionDef)):
                        complexity += 1

                # Check for common issues
                if 'eval(' in code or 'exec(' in code:
                    issues.append({"type": "security", "message": "Dangerous function usage: eval/exec"})

                if 'password' in code.lower() or 'api_key' in code.lower():
                    issues.append({"type": "security", "message": "Potential hardcoded credentials"})

                # Calculate quality score
                quality_score = 100
                quality_score -= min(complexity * 2, 30)
                quality_score -= len(issues) * 10

                return {
                    "language": language,
                    "lines_of_code": len(lines),
                    "issues": issues,
                    "complexity": complexity,
                    "quality_score": max(quality_score, 0)
                }

            except SyntaxError as e:
                issues.append({"type": "syntax", "message": f"Syntax error: {str(e)}"})

        return {
            "language": language,
            "lines_of_code": len(lines),
            "issues": issues,
            "complexity": "unknown",
            "quality_score": 50
        }

    async def _analyze_data(
        self,
        data: Any,
        analysis_type: str = "summary"
    ) -> Dict[str, Any]:
        """Analyze data"""
        logger.info(f"Data analysis: {analysis_type}")

        if not isinstance(data, (list, dict)):
            return {
                "analysis_type": analysis_type,
                "error": "Data must be a list or dictionary"
            }

        insights = []

        if isinstance(data, list):
            count = len(data)
            insights.append(f"Total items: {count}")

            if count > 0 and all(isinstance(x, (int, float)) for x in data):
                avg = sum(data) / count
                insights.append(f"Average: {avg:.2f}")
                insights.append(f"Min: {min(data)}, Max: {max(data)}")

        elif isinstance(data, dict):
            insights.append(f"Total keys: {len(data)}")
            for key, value in list(data.items())[:5]:
                insights.append(f"{key}: {type(value).__name__}")

        return {
            "analysis_type": analysis_type,
            "summary": f"Analyzed {type(data).__name__} data",
            "insights": insights
        }

    async def _summarize_text(
        self,
        text: str,
        max_length: int = 100
    ) -> Dict[str, Any]:
        """Summarize text"""
        logger.info(f"Summarizing text ({len(text)} chars)")

        try:
            from core.services.lightweight_llm import get_lightweight_llm_service
            llm = get_lightweight_llm_service()

            prompt = f"Summarize the following text in {max_length} words or less:\n\n{text}\n\nSummary:"

            result = await llm.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=max_length * 2,
                agent_type="conversation_summarizer"
            )

            summary = result.get("content", "").strip()

            return {
                "original_length": len(text),
                "summary": summary,
                "summary_length": len(summary)
            }

        except Exception as e:
            logger.error(f"LLM summarization failed: {e}")
            words = text.split()[:max_length]
            summary = ' '.join(words) + "..."
            return {
                "original_length": len(text),
                "summary": summary,
                "summary_length": len(summary)
            }

    async def _analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """Analyze sentiment"""
        logger.info(f"Sentiment analysis ({len(text)} chars)")

        try:
            from core.services.lightweight_llm import get_lightweight_llm_service
            llm = get_lightweight_llm_service()

            prompt = f"Analyze the sentiment of this text and respond with ONLY one word: positive, negative, or neutral.\n\nText: {text}\n\nSentiment:"

            result = await llm.generate(
                prompt=prompt,
                temperature=0.1,
                max_tokens=10,
                agent_type="safety_classifier"
            )

            sentiment = result.get("content", "neutral").strip().lower()
            if sentiment not in ["positive", "negative", "neutral"]:
                sentiment = "neutral"

            score = 0.7 if sentiment == "positive" else (-0.7 if sentiment == "negative" else 0.0)

            return {
                "sentiment": sentiment,
                "score": score,
                "confidence": 0.85
            }

        except Exception as e:
            logger.error(f"Sentiment analysis failed: {e}")
            positive_words = ['good', 'great', 'excellent', 'amazing', 'wonderful']
            negative_words = ['bad', 'terrible', 'awful', 'horrible', 'poor']

            text_lower = text.lower()
            pos_count = sum(1 for word in positive_words if word in text_lower)
            neg_count = sum(1 for word in negative_words if word in text_lower)

            if pos_count > neg_count:
                sentiment = "positive"
                score = 0.7
            elif neg_count > pos_count:
                sentiment = "negative"
                score = -0.7
            else:
                sentiment = "neutral"
                score = 0.0

            return {
                "sentiment": sentiment,
                "score": score,
                "confidence": 0.85
            }

    async def _analyze_image(
        self,
        image_url: str,
        analysis_type: str = "objects"
    ) -> Dict[str, Any]:
        """Analyze image"""
        logger.info(f"Image analysis: {image_url} ({analysis_type})")

        try:
            from core.services.lumen_vision import get_lumen_vision
            vision = get_lumen_vision()

            result = await vision.analyze_image(
                image_url=image_url,
                task=analysis_type
            )

            return {
                "image_url": image_url,
                "analysis_type": analysis_type,
                "objects": result.get("objects", []),
                "labels": result.get("labels", []),
                "description": result.get("description", "")
            }

        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return {
                "image_url": image_url,
                "analysis_type": analysis_type,
                "objects": [],
                "labels": [],
                "error": str(e)
            }

    async def _translate_text(
        self,
        text: str,
        target_language: str,
        source_language: str = "auto"
    ) -> Dict[str, Any]:
        """Translate text"""
        logger.info(f"Translation: {source_language} -> {target_language}")

        try:
            from core.services.unified_llm import get_llm_service
            llm = get_llm_service()

            prompt = f"Translate the following text to {target_language}. Return ONLY the translation, no explanations.\n\nText: {text}\n\nTranslation:"

            result = await llm.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=len(text) * 2,
                agent_type="chat"
            )

            translation = result.get("content", "").strip()

            return {
                "original_text": text,
                "translated_text": translation,
                "source_language": source_language,
                "target_language": target_language
            }

        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return {
                "original_text": text,
                "translated_text": f"[Translation to {target_language} failed]",
                "source_language": source_language,
                "target_language": target_language,
                "error": str(e)
            }

    async def _validate_email(self, email: str) -> Dict[str, Any]:
        """Validate email"""
        # Simple regex validation
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        is_valid = bool(re.match(email_regex, email))

        return {
            "email": email,
            "is_valid": is_valid,
            "format_valid": is_valid
        }

    async def _validate_url(
        self,
        url: str,
        check_accessible: bool = False
    ) -> Dict[str, Any]:
        """Validate URL"""
        url_regex = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
        is_valid = bool(re.match(url_regex, url))

        result = {
            "url": url,
            "is_valid": is_valid,
            "format_valid": is_valid
        }

        if check_accessible and is_valid:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                        result["accessible"] = response.status < 400
                        result["status_code"] = response.status
            except Exception as e:
                result["accessible"] = False
                result["error"] = str(e)

        return result

    async def _calculate(self, expression: str) -> Dict[str, Any]:
        """Safe calculator"""
        try:
            # Whitelist safe characters
            safe_chars = set('0123456789+-*/()., ')
            if not all(c in safe_chars for c in expression):
                return {
                    "expression": expression,
                    "error": "Invalid characters in expression"
                }

            # Evaluate safely
            result = eval(expression, {"__builtins__": {}}, {})

            return {
                "expression": expression,
                "result": result
            }

        except Exception as e:
            return {
                "expression": expression,
                "error": str(e)
            }

    def get_usage_stats(self) -> Dict[str, int]:
        """Get tool usage statistics"""
        return self.usage_stats.copy()


# ============================================================================
# Individual Tool Classes
# ============================================================================


class GenerateEmbeddingTool(Tool):
    """Generate embeddings for text using AI models"""

    def __init__(self):
        super().__init__()
        self.name = "generate_embedding"
        self.description = "Generate vector embeddings for text using AI models"
        self.parameters = [
            RegistryToolParameter(
                name="text",
                type="string",
                description="Text to generate embeddings for",
                required=True
            ),
            RegistryToolParameter(
                name="model",
                type="string",
                description="Embedding model to use",
                required=False,
                default="text-embedding-3-small"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_embedding",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_EMBEDDING,
                    description="Generate vector embeddings for semantic understanding",
                    input_types=["text"],
                    output_types=["embedding_vector"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.TRANSFORM_DATA,
                    description="Transform text into numerical vector representations",
                    input_types=["text"],
                    output_types=["vector"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Generate embeddings"""
        text = kwargs.get("text", "")
        model = kwargs.get("model", "text-embedding-3-small")

        try:
            from core.services.unified_llm import get_llm_service
            llm = get_llm_service()

            # Generate embeddings using LLM service
            embeddings = await llm.generate_embeddings(text, model=model)

            return ToolResult(
                success=True,
                output={"embeddings": embeddings, "model": model, "text_length": len(text)}
            )
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class QueryMemoryTool(Tool):
    """Query the memory system for relevant information using semantic search and tags"""

    def __init__(self):
        super().__init__()
        self.name = "query_memory"
        self.description = "Query memory system using semantic search. Returns relevant memories based on similarity to query text. Can filter by tags for specific categories."
        self.parameters = [
            RegistryToolParameter(
                name="query",
                type="string",
                description="Natural language query to search memory for (e.g., 'project structure', 'dependencies found')",
                required=True
            ),
            RegistryToolParameter(
                name="tags",
                type="array",
                description="Optional tags to filter results (e.g., ['research', 'tools'])",
                required=False,
                default=[]
            ),
            RegistryToolParameter(
                name="limit",
                type="number",
                description="Maximum number of results to return",
                required=False,
                default=5
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="query_memory",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RETRIEVE_MEMORY,
                    description="Retrieve relevant memories using semantic search",
                    input_types=["query_text", "tags"],
                    output_types=["memory_records"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.SEMANTIC_SEARCH,
                    description="Search memories using semantic similarity",
                    input_types=["query_text"],
                    output_types=["search_results"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.QUERY_KNOWLEDGE,
                    description="Query stored knowledge base",
                    input_types=["query_text", "filters"],
                    output_types=["knowledge_items"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Query memory using semantic search"""
        query = kwargs.get("query", "")
        tags = kwargs.get("tags", [])
        limit = int(kwargs.get("limit", 5))

        try:
            from core.memory import get_memory_agent

            # Get memory agent singleton
            memory_agent = await get_memory_agent()

            # Use semantic search for natural language queries
            success, results = await memory_agent.search_memories(
                query=query,
                limit=limit,
                min_similarity=0.6  # Lower threshold for research tasks
            )

            if not success:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Memory search failed"
                )

            # If tags provided, also query by tags and merge results
            if tags:
                tag_success, tag_results = await memory_agent.query_by_tags(
                    tags=tags,
                    limit=limit
                )

                if tag_success and tag_results:
                    # Merge and deduplicate by memory_id
                    seen_ids = set()
                    merged = []
                    for item in (results + tag_results):
                        # MemoryItem objects have attributes, not dict keys
                        mem_id = getattr(item, 'memory_id', None) or getattr(item, 'id', None)
                        if mem_id and mem_id not in seen_ids:
                            seen_ids.add(mem_id)
                            merged.append(item)
                    results = merged[:limit]

            # Format results for agent consumption
            formatted_results = []
            for item in results:
                # MemoryItem objects have attributes, not dict keys
                formatted_results.append({
                    "content": getattr(item, 'content', ''),
                    "tags": getattr(item, 'tags', []),
                    "importance": getattr(item, 'importance_score', 0.0),
                    "created_at": str(getattr(item, 'created_at', ''))
                })

            return ToolResult(
                success=True,
                output={
                    "results": formatted_results,
                    "count": len(formatted_results),
                    "query": query,
                    "tags_used": tags
                }
            )
        except Exception as e:
            logger.error(f"Failed to query memory: {e}")
            import traceback
            traceback.print_exc()
            return ToolResult(success=False, output=None, error=str(e))


class StoreMemoryTool(Tool):
    """Store information in the memory system with semantic indexing and tagging"""

    def __init__(self):
        super().__init__()
        self.name = "store_memory"
        self.description = "Store discoveries/findings in memory with semantic indexing. Use tags to categorize for later retrieval. Stored memories persist across sessions."
        self.parameters = [
            RegistryToolParameter(
                name="content",
                type="string",
                description="Content to store in memory (e.g., research findings, discovered facts)",
                required=True
            ),
            RegistryToolParameter(
                name="memory_type",
                type="string",
                description="Type of memory: 'semantic' (knowledge/facts), 'episodic' (events), 'procedural' (procedures)",
                required=False,
                default="semantic"
            ),
            RegistryToolParameter(
                name="tags",
                type="array",
                description="Tags for categorization (e.g., ['research', 'dependencies', 'tools'])",
                required=False,
                default=[]
            ),
            RegistryToolParameter(
                name="importance",
                type="number",
                description="Importance score 0.0-1.0 (higher = more important)",
                required=False,
                default=0.7
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="store_memory",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONSOLIDATE_MEMORY,
                    description="Store and consolidate information in long-term memory",
                    input_types=["content", "memory_type", "tags"],
                    output_types=["memory_id"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.CONSOLIDATE_KNOWLEDGE,
                    description="Build and maintain knowledge base with categorization",
                    input_types=["content", "tags", "importance"],
                    output_types=["storage_confirmation"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.WRITE_DATA,
                    description="Persist data to memory storage",
                    input_types=["content"],
                    output_types=["write_result"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.MEDIUM,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.UPDATE_BELIEFS,
                    description="Update belief state based on new information",
                    input_types=["belief", "evidence"],
                    output_types=["updated_belief"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.FORGET_KNOWLEDGE,
                    description="Selectively forget outdated knowledge",
                    input_types=["knowledge_key"],
                    output_types=["deletion_status"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=6
                ),
                CapabilityMetadata(
                    capability=Capability.UPDATE_MENTAL_MODEL,
                    description="Update mental model with new learned information",
                    input_types=["new_info"],
                    output_types=["model_update"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=False  # Multiple stores create new entries
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Store information in memory"""
        content = kwargs.get("content", "")
        memory_type_str = kwargs.get("memory_type", "semantic").lower()
        tags = kwargs.get("tags", [])
        importance = float(kwargs.get("importance", 0.7))

        try:
            from core.memory import get_memory_agent
            from core.memory.utils.interfaces import MemoryType

            # Map string type to MemoryType enum
            type_map = {
                "episodic": MemoryType.EPISODIC,
                "semantic": MemoryType.SEMANTIC,
                "procedural": MemoryType.PROCEDURAL,
                "working": MemoryType.WORKING,
                "meta": MemoryType.META
            }
            mem_type = type_map.get(memory_type_str, MemoryType.SEMANTIC)

            # Get memory agent singleton
            logger.debug(f"\n[STORE_MEMORY DEBUG] Getting memory agent singleton...")
            memory_agent = await get_memory_agent()
            logger.debug(f"[STORE_MEMORY DEBUG] Memory agent: {type(memory_agent)}")
            logger.debug(f"[STORE_MEMORY DEBUG] Memory agent initialized: {getattr(memory_agent, 'initialized', 'N/A')}")

            # Store with full metadata
            logger.debug(f"[STORE_MEMORY DEBUG] Storing memory:")
            logger.debug(f"  Content length: {len(content)} chars")
            logger.debug(f"  Memory type: {mem_type}")
            logger.debug(f"  Tags: {tags}")
            logger.debug(f"  Importance: {importance}")

            success, memory_id = await memory_agent.store_memory(
                content=content,
                memory_type=mem_type,
                importance_score=importance,
                confidence_score=0.9,  # High confidence for agent-generated content
                tags=tags,
                source_context={
                    "tool": "store_memory",
                    "agent_initiated": True,
                    "memory_type": memory_type_str
                }
            )

            logger.debug(f"[STORE_MEMORY DEBUG] Result: success={success}, memory_id={memory_id}")

            if not success:
                error_msg = f"Failed to store memory (success=False, memory_id={memory_id})"
                logger.debug(f"[STORE_MEMORY DEBUG] ERROR: {error_msg}")
                return ToolResult(
                    success=False,
                    output=None,
                    error=error_msg
                )

            return ToolResult(
                success=True,
                output={
                    "memory_id": memory_id,
                    "memory_type": memory_type_str,
                    "tags": tags,
                    "importance": importance,
                    "message": f"Stored to memory with ID: {memory_id}"
                }
            )
        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            import traceback
            traceback.print_exc()
            return ToolResult(success=False, output=None, error=str(e))


class RunInferenceTool(Tool):
    """Run ML model inference"""

    def __init__(self):
        super().__init__()
        self.name = "run_inference"
        self.description = "Run ML model inference on input data"
        self.parameters = [
            RegistryToolParameter(
                name="model_name",
                type="string",
                description="Name of the model to use",
                required=True
            ),
            RegistryToolParameter(
                name="input_data",
                type="object",
                description="Input data for inference",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="run_inference",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_INFERENCE,
                    description="Execute ML model inference on provided input",
                    input_types=["model_name", "input_data"],
                    output_types=["inference_result"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.GENERATE_EMBEDDING,
                    description="Generate predictions using ML models",
                    input_types=["model_name", "data"],
                    output_types=["prediction"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.SUMMARIZE_TEXT,
                    description="Summarize text using ML inference",
                    input_types=["text", "max_length"],
                    output_types=["summary"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Run inference"""
        model_name = kwargs.get("model_name", "")
        input_data = kwargs.get("input_data", {})

        try:
            from core.services.unified_llm import get_llm_service
            llm = get_llm_service()

            # Run inference using LLM service
            llm_result = await llm.generate(
                prompt=str(input_data),
                temperature=0.7,
                agent_type="chat"
            )

            result_text = llm_result.get("content", "")

            return ToolResult(
                success=True,
                output={"result": result_text, "model": model_name}
            )
        except Exception as e:
            logger.error(f"Failed to run inference: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class AnalyzeTrainingDataTool(Tool):
    """Analyze training data for quality and distribution"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_training_data"
        self.description = "Analyze training data for quality, distribution, and potential issues"
        self.parameters = [
            RegistryToolParameter(
                name="data",
                type="array",
                description="Training data to analyze",
                required=True
            ),
            RegistryToolParameter(
                name="data_type",
                type="string",
                description="Type of data (text, numerical, categorical)",
                required=False,
                default="text"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_training_data",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    description="Analyze training data quality and distribution",
                    input_types=["dataset", "data_type"],
                    output_types=["quality_analysis"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Assess dataset quality metrics and identify issues",
                    input_types=["dataset"],
                    output_types=["analysis_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.DETECT_ANOMALY,
                    description="Detect anomalies and quality issues in training data",
                    input_types=["dataset"],
                    output_types=["anomaly_report"],
                    latency="medium",
                    cost="low",
                    reliability="medium",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Analyze training data"""
        data = kwargs.get("data", [])
        data_type = kwargs.get("data_type", "text")

        try:
            analysis = {
                "total_samples": len(data),
                "data_type": data_type,
                "quality_score": 0.85,  # Placeholder
                "issues": [],
                "distribution": {
                    "balanced": True,
                    "samples_per_class": {}
                }
            }

            # Basic quality checks
            if len(data) < 100:
                analysis["issues"].append("Dataset may be too small for effective training")

            return ToolResult(
                success=True,
                output=analysis
            )
        except Exception as e:
            logger.error(f"Failed to analyze training data: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class GetModelInfoTool(Tool):
    """Get information about available AI models"""

    def __init__(self):
        super().__init__()
        self.name = "get_model_info"
        self.description = "Get information about available AI models and their capabilities"
        self.parameters = [
            RegistryToolParameter(
                name="model_name",
                type="string",
                description="Specific model name (optional)",
                required=False,
                default=""
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_model_info",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GET_SYSTEM_INFO,
                    description="Get information about available AI models",
                    input_types=["model_name"],
                    output_types=["model_metadata"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.LIST_DATA,
                    description="List available models and their specifications",
                    input_types=[],
                    output_types=["model_list"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=6
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Get model info"""
        model_name = kwargs.get("model_name", "")

        try:
            from core.services.unified_llm import get_llm_service
            llm = get_llm_service()

            available_models = {
                "llama-3.1-8b-instruct": {
                    "parameters": "8B",
                    "context_length": 8192,
                    "capabilities": ["chat", "reasoning", "coding"]
                }
            }

            if model_name:
                info = available_models.get(model_name, {"error": "Model not found"})
            else:
                info = available_models

            return ToolResult(
                success=True,
                output={"models": info}
            )
        except Exception as e:
            logger.error(f"Failed to get model info: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class SemanticSimilarityTool(Tool):
    """Calculate semantic similarity between texts"""

    def __init__(self):
        super().__init__()
        self.name = "semantic_similarity"
        self.description = "Calculate semantic similarity between two texts"
        self.parameters = [
            RegistryToolParameter(
                name="text1",
                type="string",
                description="First text",
                required=True
            ),
            RegistryToolParameter(
                name="text2",
                type="string",
                description="Second text",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="semantic_similarity",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_SIMILARITY,
                    description="Calculate semantic similarity between two text inputs",
                    input_types=["text1", "text2"],
                    output_types=["similarity_score"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.ANALOGICAL_REASONING,
                    description="Compare conceptual similarity between texts",
                    input_types=["text1", "text2"],
                    output_types=["comparison_result"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Calculate similarity"""
        text1 = kwargs.get("text1", "")
        text2 = kwargs.get("text2", "")

        try:
            from core.services.unified_llm import get_llm_service
            llm = get_llm_service()

            # Generate embeddings for both texts
            emb1 = await llm.generate_embeddings(text1)
            emb2 = await llm.generate_embeddings(text2)

            # Calculate cosine similarity
            import numpy as np
            similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))

            return ToolResult(
                success=True,
                output={"similarity": float(similarity)}
            )
        except Exception as e:
            # A DIFFERENT METRIC IS NOT THIS METRIC. On failure this computed
            # word-overlap Jaccard and returned it as `similarity` with
            # success=True, so anything comparing scores across calls was
            # comparing embedding cosine against bag-of-words -- silently, and
            # only `method` said so. Nothing downstream reads `method`.
            logger.error("Semantic similarity unavailable: %s", e)
            return ToolResult(
                success=False,
                output=None,
                error=(f"semantic similarity unavailable: {e}. Word-overlap is "
                       f"a different measurement and is not substituted for it."),
            )


class ExtractEntitiesTool(Tool):
    """Extract named entities from text"""

    def __init__(self):
        super().__init__()
        self.name = "extract_entities"
        self.description = "Extract named entities (people, organizations, locations) from text"
        self.parameters = [
            RegistryToolParameter(
                name="text",
                type="string",
                description="Text to extract entities from",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="extract_entities",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.EXTRACT_ENTITIES,
                    description="Extract named entities including people, organizations, locations, and dates",
                    input_types=["text"],
                    output_types=["entity_list"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.EXTRACT_PATTERNS,
                    description="Identify and extract structured patterns from text",
                    input_types=["text"],
                    output_types=["pattern_matches"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.PARSE_DATA,
                    description="Parse and categorize textual information",
                    input_types=["text"],
                    output_types=["parsed_entities"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Extract entities"""
        text = kwargs.get("text", "")

        try:
            from core.services.lightweight_llm import get_lightweight_llm_service
            llm = get_lightweight_llm_service()

            # Use LLM for entity extraction
            prompt = f"""Extract named entities from the following text. Return them as JSON with categories:
- person: People names
- organization: Companies, organizations
- location: Places, locations
- date: Dates and times
- other: Other important entities

Text: {text}

Return ONLY valid JSON."""

            result = await llm.generate(
                prompt=prompt,
                temperature=0.1,
                max_tokens=500,
                agent_type="json_classifier"
            )

            response = result.get("content", "{}")

            # Try to parse JSON response
            import json
            entities = json.loads(response)

            return ToolResult(
                success=True,
                output={"entities": entities}
            )
        except Exception as e:
            # AN EMPTY RESULT IS NOT A FINDING OF NONE. This returned every
            # entity category empty with success=True, so "extraction failed"
            # and "this text contains no people, organizations, locations or
            # dates" were the same answer to the caller.
            logger.error("Entity extraction failed: %s", e)
            return ToolResult(
                success=False,
                output=None,
                error=f"entity extraction failed: {e}",
            )


# Singleton instance
_ai_ml_tools = None


def get_ai_ml_tools() -> AIMLTools:
    """Get global AI/ML tools instance"""
    global _ai_ml_tools
    if _ai_ml_tools is None:
        _ai_ml_tools = AIMLTools()
    return _ai_ml_tools


# CLI test
async def main():
    """Test AI/ML tools"""
    logging.basicConfig(level=logging.INFO)

    tools = get_ai_ml_tools()

    print("\n=== AI/ML Tools Test ===")
    print(f"Registered tools: {len(tools.list_tools())}")

    # Test search tool
    result = await tools.execute_tool("search_web", {"query": "AI news", "num_results": 3})
    print(f"\nSearch result: {result['success']}")

    # Test sentiment analysis
    result = await tools.execute_tool("analyze_sentiment", {"text": "This is a great day!"})
    print(f"Sentiment: {result['result']['sentiment']}")

    # Test calculator
    result = await tools.execute_tool("calculate", {"expression": "2 + 2"})
    print(f"Calculator: {result['result']['result']}")

    # Get tool definitions for LLM
    definitions = tools.get_tool_definitions()
    print(f"\nTool definitions: {len(definitions)} tools")


if __name__ == "__main__":
    asyncio.run(main())
