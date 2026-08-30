#!/usr/bin/env python3
"""
Research Tools
==============
High-level research capabilities using multi-source API registry

Tools:
- conduct_research: Multi-source research with auto-source selection
- search_academic: Academic paper search
- search_data: Government/statistical data search
- search_news: News and current events search

Author: Torin AI Team
"""

import json
import logging
import asyncio
import re
import hashlib
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from urllib.parse import urlparse

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata, RiskLevel
from .network_tools import HttpRequestTool


logger = logging.getLogger(__name__)


class TopicClassifier:
    """
    Classify research topics to auto-select relevant APIs

    Uses keyword matching and semantic analysis to determine
    which API categories are most relevant for a query.
    """

    # Category keyword mappings
    CATEGORY_KEYWORDS = {
        "academic": [
            "research", "paper", "study", "journal", "publication", "thesis",
            "science", "scientific", "scholar", "academic", "physics", "chemistry",
            "biology", "mathematics", "computer science", "ai", "ml", "machine learning",
            "deep learning", "neural", "quantum", "theory", "experiment"
        ],
        "government_data": [
            "census", "statistics", "government", "federal", "national", "policy",
            "legislation", "regulation", "demographics", "population", "economic data",
            "gdp", "unemployment", "inflation", "trade", "import", "export"
        ],
        "finance": [
            "stock", "market", "trading", "investment", "portfolio", "ticker",
            "price", "dividend", "earnings", "crypto", "bitcoin", "ethereum",
            "forex", "exchange rate", "nasdaq", "dow jones", "s&p 500", "financial"
        ],
        "news": [
            "news", "article", "headline", "breaking", "current events", "today",
            "recent", "latest", "happening", "report", "press", "media", "journalism"
        ],
        "knowledge": [
            "what is", "define", "definition", "explain", "encyclopedia", "dictionary",
            "meaning", "information about", "facts about", "tell me about", "history of",
            "who is", "who was", "where is", "when did"
        ],
        "code_development": [
            "code", "programming", "developer", "github", "repository", "library",
            "package", "npm", "pypi", "api", "framework", "sdk", "documentation",
            "bug", "issue", "pull request", "commit", "git"
        ],
        "cultural_heritage": [
            "museum", "art", "artifact", "historical", "archive", "collection",
            "exhibition", "cultural", "heritage", "antiquity", "ancient", "medieval",
            "renaissance", "painting", "sculpture", "manuscript"
        ],
        "weather_climate": [
            "weather", "forecast", "temperature", "rain", "snow", "climate",
            "precipitation", "humidity", "wind", "storm", "hurricane", "tornado"
        ],
        "geography_maps": [
            "location", "address", "coordinates", "map", "directions", "navigation",
            "place", "city", "country", "geocode", "latitude", "longitude"
        ],
        "educational_entertainment": [
            "fun facts", "trivia", "interesting", "cool", "amazing", "random",
            "did you know", "joke", "fun", "entertainment", "casual"
        ]
    }

    @classmethod
    def classify(cls, query: str, max_categories: int = 3) -> List[str]:
        """
        Classify a query into relevant API categories

        Args:
            query: Research query/topic
            max_categories: Maximum categories to return

        Returns:
            List of category names sorted by relevance
        """
        query_lower = query.lower()
        scores = {}

        # Score each category based on keyword matches
        for category, keywords in cls.CATEGORY_KEYWORDS.items():
            score = 0
            for keyword in keywords:
                if keyword in query_lower:
                    # Longer keywords = more specific = higher weight
                    score += len(keyword.split())

            if score > 0:
                scores[category] = score

        # If no matches, default to knowledge and educational
        if not scores:
            return ["knowledge", "educational_entertainment"]

        # Sort by score and return top categories
        sorted_categories = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [cat for cat, _ in sorted_categories[:max_categories]]


class ConductResearchTool(Tool):
    """
    High-level multi-source research tool

    Automatically selects and queries appropriate APIs based on topic,
    synthesizes results from multiple sources, and returns comprehensive findings.
    """

    def __init__(self):
        super().__init__()
        self.name = "conduct_research"
        self.description = "Conduct comprehensive multi-source research on any topic with automatic source selection"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="topic",
                type="string",
                description=(
                    "The research subject or question. "
                    "IMPORTANT: this parameter is named 'topic', NOT 'query', 'search_query', or 'q'. "
                    "Example: conduct_research(topic='AI agent architectures 2024')"
                ),
                required=True
            ),
            ToolParameter(
                name="max_sources",
                type="number",
                description=(
                    "Maximum number of sources to query (1-20, default 5). "
                    "IMPORTANT: this parameter is named 'max_sources', NOT 'limit' or 'num_results'."
                ),
                required=False,
                default=5,
                min_value=1,
                max_value=20
            ),
            ToolParameter(
                name="categories",
                type="array",
                description="Specific categories to search (auto-detected if not provided)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="conduct_research",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="ConductResearch capability"
                ),
                CapabilityMetadata(
                    capability=Capability.SUMMARIZE_TEXT,
                    description="Summarize research findings and documents",
                    input_types=["text"],
                    output_types=["summary"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.EXPLORE_DOMAIN,
                    description="Explore new knowledge domains through research",
                    input_types=["domain"],
                    output_types=["domain_overview"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ]
        )

        self.api_registry = self._load_api_registry()
        self.http_tool = HttpRequestTool()

    def _load_api_registry(self) -> Dict[str, Any]:
        """Load API registry from JSON file"""
        registry_path = Path(__file__).parent / "api_registry.json"

        if not registry_path.exists():
            logger.warning(f"API registry not found at {registry_path}")
            return {"version": "0.0", "categories": {}}

        try:
            with open(registry_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load API registry: {e}")
            return {"version": "0.0", "categories": {}}

    def _select_apis(self, categories: List[str], max_sources: int) -> List[Dict[str, Any]]:
        """
        Select best APIs from registry based on categories

        Args:
            categories: List of category names
            max_sources: Maximum APIs to select

        Returns:
            List of API configurations sorted by quality score
        """
        selected_apis = []

        for category in categories:
            if category in self.api_registry.get("categories", {}):
                category_apis = self.api_registry["categories"][category].get("apis", [])

                # Filter for tested APIs with high quality scores
                for api in category_apis:
                    if api.get("tested", False) and api.get("quality_score", 0) >= 0.7:
                        api_copy = api.copy()
                        api_copy["category"] = category
                        selected_apis.append(api_copy)

        # Sort by quality score (descending)
        selected_apis.sort(key=lambda x: x.get("quality_score", 0), reverse=True)

        return selected_apis[:max_sources]

    async def _query_api(self, api: Dict[str, Any], topic: str) -> Optional[Dict[str, Any]]:
        """
        Query a specific API

        Args:
            api: API configuration from registry
            topic: Research topic

        Returns:
            API response data or None if failed
        """
        try:
            import urllib.parse as _up

            # Build query based on API type
            url = api["base_url"]
            _enc = _up.quote_plus(topic)

            # API-specific query building
            api_name = api["name"].lower()

            if "arxiv" in api_name:
                url = f"{url}?search_query=all:{_enc}&max_results=5"

            elif "pubmed" in api_name:
                url = f"{url}?db=pubmed&term={_enc}&retmode=json&retmax=5"

            elif "wikipedia" in api_name:
                url = f"{url}?action=query&list=search&srsearch={_enc}&format=json&srlimit=5"

            elif "wikidata" in api_name:
                url = f"{url}?action=wbsearchentities&search={_enc}&language=en&format=json&limit=5"

            elif "github" in api_name:
                url = f"{url}/search/repositories?q={_enc}&sort=stars&order=desc&per_page=5"

            elif "world bank" in api_name or "worldbank" in api_name:
                url = f"{url}/v2/indicator?format=json&per_page=5"

            elif "rest countries" in api_name:
                # REST Countries searches by country name — use first word as approximation
                # for general topics this will 404, which is expected and handled downstream
                _first_word = _up.quote_plus(topic.split()[0])
                url = f"{url}/name/{_first_word}"

            elif "open-meteo" in api_name:
                # Weather requires coordinates - skip for general topics
                return None

            elif "met museum" in api_name or "metropolitan" in api_name:
                url = f"{url}/search?q={_enc}"

            elif "free dictionary" in api_name or "dictionary" in api_name:
                # Dictionary API uses path-based lookup: /api/v2/entries/en/<word>
                _first_word = _up.quote_plus(topic.split()[0].lower())
                url = f"{url}/{_first_word}"

            elif "nasa" in api_name or "apod" in api_name:
                # NASA APOD returns today's picture — no topic search, use as context enrichment
                url = f"{url}?api_key=DEMO_KEY"

            else:
                # Generic: append as query param
                url = f"{url}?q={_enc}"

            # Make request
            result = await self.http_tool.execute(
                url=url,
                method="GET",
                timeout=10
            )

            if result.success:
                return {
                    "source": api["name"],
                    "category": api.get("category", "unknown"),
                    "quality_score": api.get("quality_score", 0),
                    "data": result.output.get("content") or result.output.get("body", ""),
                    "url": url
                }
            else:
                _status = result.output.get("status") if result.output else None
                _err = result.error or (f"HTTP {_status}" if _status else "unknown error")
                logger.warning(f"Failed to query {api['name']}: {_err}")
                return None

        except Exception as e:
            logger.error(f"Error querying {api.get('name', 'unknown')}: {e}")
            return None

    def _synthesize_results(self, results: List[Dict[str, Any]], topic: str) -> str:
        """
        Synthesize results from multiple sources into coherent summary

        Args:
            results: List of API responses
            topic: Original research topic

        Returns:
            Formatted research summary
        """
        if not results:
            return f"No results found for topic: {topic}"

        synthesis = f"# Research Results: {topic}\n\n"
        synthesis += f"**Sources queried:** {len(results)}\n"
        synthesis += f"**Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        # Group by category
        by_category = {}
        for result in results:
            category = result.get("category", "unknown")
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(result)

        # Format results by category
        for category, category_results in by_category.items():
            synthesis += f"## {category.replace('_', ' ').title()}\n\n"

            for result in category_results:
                source = result.get("source", "Unknown")
                quality = result.get("quality_score", 0)
                data = result.get("data", {})

                synthesis += f"### {source} (Quality: {quality:.2f})\n"

                # Extract key information from response
                # This is simplified - actual extraction would be API-specific
                if isinstance(data, dict):
                    # Try to find useful fields
                    if "results" in data:
                        synthesis += f"- Found {len(data['results'])} results\n"
                    if "total" in data:
                        synthesis += f"- Total available: {data['total']}\n"
                    if "description" in data:
                        synthesis += f"- {data['description']}\n"

                synthesis += f"- URL: {result.get('url', 'N/A')}\n\n"

        return synthesis


    async def _web_search_fallback(self, topic: str, max_results: int = 5,
                                   categories: Optional[List[str]] = None):
        """Research via the registered web_search tool.

        web_search is verified working (live results), it is simply not listed
        in api_registry.json. Returning None means the fallback itself failed,
        so the caller can report an honest failure rather than a fake success.
        """
        try:
            from core.tools.tool_registry import get_tool_registry
            tool = get_tool_registry().get_tool("web_search")
            if tool is None:
                return None
            res = await tool.execute(query=topic, max_results=max_results)
            if not getattr(res, "success", False):
                return None
            out = getattr(res, "output", None) or {}
            results = out.get("results") or []
            if not results:
                return None
            return {
                "topic": topic,
                # Carried through: submit_research_result files concepts under
                # the classified category, and dropping it here made the
                # fallback path produce research with nowhere to put it.
                "categories": categories or [],
                "sources_queried": 1,
                "sources_successful": 1,
                "apis_used": ["web_search"],
                "raw_results": results,
                "synthesis": self._synthesize_results(
                    [{"source": "web_search", "data": results}], topic
                ),
            }
        except Exception as e:
            logger.warning(f"web_search fallback failed for '{topic}': {e}")
            return None

    async def execute(self, topic: str, max_sources: int = 5,
                     categories: Optional[List[str]] = None) -> ToolResult:
        """
        Execute comprehensive research

        Args:
            topic: Research topic or question
            max_sources: Maximum sources to query
            categories: Specific categories (auto-detected if None)

        Returns:
            ToolResult with synthesized research findings
        """
        start_time = datetime.now()

        try:
            # Step 1: Classify topic if categories not provided
            if not categories:
                categories = TopicClassifier.classify(topic, max_categories=3)
                logger.info(f"Auto-classified '{topic}' into categories: {categories}")

            # Step 2: Select best APIs
            selected_apis = self._select_apis(categories, max_sources)

            # FALLBACK: web_search is a registered, working tool that returns
            # real results, but it lives outside api_registry.json so the
            # aggregator never consulted it. Meanwhile 61 of the registry's 75
            # APIs are unmarked-untested and therefore invisible to
            # _select_apis, so whole categories (news, finance, geography) have
            # ZERO usable sources -- a technical topic classified into one of
            # them hard-failed while a working search tool sat idle.
            #
            # Research must not fail while the system can plainly research.
            if not selected_apis:
                logger.info(
                    f"No registry API qualified for {categories} — "
                    f"falling back to web_search"
                )
                fallback = await self._web_search_fallback(topic, max_sources, categories)
                if fallback is not None:
                    execution_time = (datetime.now() - start_time).total_seconds()
                    return ToolResult(
                        success=True,
                        output=fallback,
                        error=None,
                        execution_time=execution_time,
                        tool_name=self.name,
                        parameters={"topic": topic, "max_sources": max_sources,
                                    "categories": categories},
                    )

            if not selected_apis:
                return ToolResult(
                    success=False,
                    output=f"No suitable APIs found for categories: {categories}",
                    error="No APIs available",
                    tool_name=self.name,
                    parameters={"topic": topic, "max_sources": max_sources}
                )

            logger.info(f"Selected {len(selected_apis)} APIs: {[api['name'] for api in selected_apis]}")

            # Step 3: Query APIs in parallel
            tasks = [self._query_api(api, topic) for api in selected_apis]
            results = await asyncio.gather(*tasks)

            # Filter out None results
            successful_results = [r for r in results if r is not None]

            # Step 4: Synthesize results
            synthesis = self._synthesize_results(successful_results, topic)

            execution_time = (datetime.now() - start_time).total_seconds()

            # If all APIs failed, report as failure so the caller knows
            # not to treat this as usable research data.
            if len(successful_results) == 0:
                # Same reasoning as above: every registry API failed, but
                # web_search may still succeed. Try it before declaring defeat.
                fallback = await self._web_search_fallback(topic, max_sources, categories)
                if fallback is not None:
                    fallback["note"] = (
                        f"all {len(selected_apis)} registry APIs failed; "
                        f"results from web_search fallback"
                    )
                    return ToolResult(
                        success=True,
                        output=fallback,
                        error=None,
                        execution_time=execution_time,
                        tool_name=self.name,
                        parameters={"topic": topic, "max_sources": max_sources,
                                    "categories": categories},
                    )
                return ToolResult(
                    success=False,
                    output=None,
                    error=(
                        f"conduct_research: all {len(selected_apis)} APIs failed for topic '{topic}'. "
                        f"APIs tried: {[api['name'] for api in selected_apis]}. "
                        "No research data was retrieved. "
                        "Try web_search or web_fetch directly with specific URLs instead."
                    ),
                    execution_time=execution_time,
                    tool_name=self.name,
                    parameters={"topic": topic, "max_sources": max_sources, "categories": categories}
                )

            return ToolResult(
                success=True,
                output={
                    "topic": topic,
                    "categories": categories,
                    "sources_queried": len(selected_apis),
                    "sources_successful": len(successful_results),
                    "apis_used": [api["name"] for api in selected_apis],
                    "synthesis": synthesis,
                    "raw_results": successful_results
                },
                execution_time=execution_time,
                tool_name=self.name,
                parameters={"topic": topic, "max_sources": max_sources, "categories": categories}
            )

        except Exception as e:
            logger.error(f"Research failed for topic '{topic}': {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e),
                tool_name=self.name,
                parameters={"topic": topic, "max_sources": max_sources}
            )


class SearchAcademicTool(Tool):
    """Specialized academic research tool"""

    def __init__(self):
        super().__init__()
        self.name = "search_academic"
        self.description = "Search academic papers, journals, and scholarly publications"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="query",
                type="string",
                description="Academic search query",
                required=True
            ),
            ToolParameter(
                name="max_results",
                type="number",
                description="Maximum results to return",
                required=False,
                default=10,
                min_value=1,
                max_value=100
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="search_academic",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="SearchAcademic capability"
                ),
                CapabilityMetadata(
                    capability=Capability.SEARCH_ACADEMIC,
                    description="Search academic databases for research papers",
                    input_types=["query", "filters"],
                    output_types=["papers"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                )
            ]
        )
        self.research_tool = ConductResearchTool()

    async def execute(self, query: str, max_results: int = 10) -> ToolResult:
        """Execute academic search"""
        return await self.research_tool.execute(
            topic=query,
            max_sources=min(max_results // 2, 5),
            categories=["academic", "knowledge"]
        )


class SearchDataTool(Tool):
    """Specialized data/statistics research tool"""

    def __init__(self):
        super().__init__()
        self.name = "search_data"
        self.description = "Search government data, statistics, and economic indicators"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="query",
                type="string",
                description="Data search query",
                required=True
            ),
            ToolParameter(
                name="max_results",
                type="number",
                description="Maximum results to return",
                required=False,
                default=10,
                min_value=1,
                max_value=100
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="search_data",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="SearchData capability"
                )
            ]
        )
        self.research_tool = ConductResearchTool()

    async def execute(self, query: str, max_results: int = 10) -> ToolResult:
        """Execute data search"""
        return await self.research_tool.execute(
            topic=query,
            max_sources=min(max_results // 2, 5),
            categories=["government_data", "finance"]
        )


class SearchNewsTool(Tool):
    """Specialized news search tool"""

    def __init__(self):
        super().__init__()
        self.name = "search_news"
        self.description = "Search news articles and current events"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="query",
                type="string",
                description="News search query",
                required=True
            ),
            ToolParameter(
                name="max_results",
                type="number",
                description="Maximum results to return",
                required=False,
                default=10,
                min_value=1,
                max_value=100
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="search_news",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="SearchNews capability"
                )
            ]
        )
        self.research_tool = ConductResearchTool()

    async def execute(self, query: str, max_results: int = 10) -> ToolResult:
        """Execute news search"""
        return await self.research_tool.execute(
            topic=query,
            max_sources=min(max_results // 2, 5),
            categories=["news", "knowledge"]
        )


# ===== RESEARCH INFRASTRUCTURE =====


class SourceCredibilityScorer:
    """
    Evaluate source credibility and rank results

    Scores sources based on:
    - Domain reputation (academic, government, established media)
    - Content quality indicators (citations, references, author credentials)
    - Freshness (recency of content)
    - Cross-validation (corroboration from other sources)
    """

    # Domain reputation scores (0.0 to 1.0)
    DOMAIN_REPUTATION = {
        # Academic
        ".edu": 0.9,
        "arxiv.org": 0.95,
        "pubmed.ncbi.nlm.nih.gov": 0.95,
        "scholar.google.com": 0.9,
        "ieee.org": 0.9,
        "acm.org": 0.9,
        "nature.com": 0.95,
        "science.org": 0.95,

        # Government
        ".gov": 0.9,
        "census.gov": 0.95,
        "data.gov": 0.9,
        "who.int": 0.9,
        "europa.eu": 0.85,

        # Established media
        "reuters.com": 0.8,
        "apnews.com": 0.8,
        "bbc.com": 0.75,
        "nytimes.com": 0.75,
        "wsj.com": 0.75,

        # Reference/Knowledge
        "wikipedia.org": 0.7,
        "britannica.com": 0.8,

        # Technical
        "github.com": 0.7,
        "stackoverflow.com": 0.65,

        # Default scores by TLD
        ".org": 0.5,
        ".com": 0.4,
        ".net": 0.4,
    }

    @classmethod
    def score_source(cls, url: str, content: Dict[str, Any],
                     timestamp: Optional[datetime] = None,
                     corroborated: bool = False) -> Dict[str, Any]:
        """
        Score a source's credibility

        Args:
            url: Source URL
            content: Response content/metadata
            timestamp: Publication/fetch timestamp
            corroborated: Whether content is corroborated by other sources

        Returns:
            Dict with credibility score and breakdown
        """
        scores = {
            "domain_reputation": 0.0,
            "content_quality": 0.0,
            "freshness": 0.0,
            "corroboration": 0.0,
            "overall": 0.0
        }

        # Domain reputation (40% weight)
        domain = urlparse(url).netloc.lower()
        domain_score = 0.4  # Default

        for pattern, score in cls.DOMAIN_REPUTATION.items():
            if pattern in domain:
                domain_score = score
                break

        scores["domain_reputation"] = domain_score

        # Content quality (30% weight)
        quality_indicators = 0

        # Check for citations/references
        if isinstance(content, dict):
            if any(key in content for key in ["references", "citations", "bibliography"]):
                quality_indicators += 1
            if any(key in content for key in ["author", "authors", "byline"]):
                quality_indicators += 1
            if any(key in content for key in ["doi", "pmid", "arxiv_id"]):
                quality_indicators += 1
            if "abstract" in content or "summary" in content:
                quality_indicators += 1

        scores["content_quality"] = min(quality_indicators / 4.0, 1.0)

        # Freshness (15% weight)
        if timestamp:
            age_days = (datetime.now() - timestamp).days
            if age_days < 7:
                freshness = 1.0
            elif age_days < 30:
                freshness = 0.9
            elif age_days < 180:
                freshness = 0.7
            elif age_days < 365:
                freshness = 0.5
            else:
                freshness = 0.3
            scores["freshness"] = freshness
        else:
            scores["freshness"] = 0.5  # Unknown

        # Corroboration (15% weight)
        scores["corroboration"] = 1.0 if corroborated else 0.0

        # Calculate overall score (weighted average)
        scores["overall"] = (
            scores["domain_reputation"] * 0.40 +
            scores["content_quality"] * 0.30 +
            scores["freshness"] * 0.15 +
            scores["corroboration"] * 0.15
        )

        return scores

    @classmethod
    def rank_sources(cls, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Rank sources by credibility

        Args:
            sources: List of source dicts with url, content, timestamp

        Returns:
            Sorted list with credibility scores added
        """
        # Score all sources
        scored_sources = []
        for source in sources:
            credibility = cls.score_source(
                url=source.get("url", ""),
                content=source.get("data", {}),
                timestamp=source.get("timestamp"),
                corroborated=source.get("corroborated", False)
            )
            source["credibility"] = credibility
            scored_sources.append(source)

        # Sort by overall credibility score
        scored_sources.sort(key=lambda x: x["credibility"]["overall"], reverse=True)

        return scored_sources


class DeduplicationEngine:
    """
    Detect and merge duplicate results from different sources

    Uses multiple strategies:
    - Content hashing (exact duplicates)
    - Fuzzy matching (similar titles/abstracts)
    - URL canonicalization (same page, different URLs)
    - DOI/identifier matching (academic papers)
    """

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """Compute SHA256 hash of normalized content"""
        # Normalize: lowercase, remove extra whitespace
        normalized = " ".join(content.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def extract_identifiers(data: Dict[str, Any]) -> Set[str]:
        """Extract unique identifiers (DOI, PMID, arXiv ID, etc.)"""
        identifiers = set()

        # Common identifier fields
        id_fields = ["doi", "pmid", "arxiv_id", "isbn", "issn", "url"]

        for field in id_fields:
            if field in data and data[field]:
                identifiers.add(f"{field}:{data[field]}")

        return identifiers

    @staticmethod
    def fuzzy_similarity(text1: str, text2: str) -> float:
        """
        Compute fuzzy similarity between two texts

        Uses Jaccard similarity on word sets
        """
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    @classmethod
    def deduplicate(cls, sources: List[Dict[str, Any]],
                   similarity_threshold: float = 0.8) -> List[Dict[str, Any]]:
        """
        Deduplicate sources

        Args:
            sources: List of source results
            similarity_threshold: Threshold for fuzzy matching (0.0 to 1.0)

        Returns:
            Deduplicated list with merged duplicates
        """
        unique_sources = []
        seen_hashes = set()
        seen_identifiers = set()

        for source in sources:
            is_duplicate = False
            data = source.get("data", {})

            # Strategy 1: Identifier matching
            identifiers = cls.extract_identifiers(data)
            if identifiers & seen_identifiers:
                # Merge with existing source
                is_duplicate = True
                for existing in unique_sources:
                    existing_ids = cls.extract_identifiers(existing.get("data", {}))
                    if identifiers & existing_ids:
                        # Merge sources
                        if "duplicate_sources" not in existing:
                            existing["duplicate_sources"] = []
                        existing["duplicate_sources"].append(source.get("source", "unknown"))
                        break

            # Strategy 2: Content hashing
            if not is_duplicate and "title" in data:
                content_hash = cls.compute_content_hash(data["title"])
                if content_hash in seen_hashes:
                    is_duplicate = True
                    # Find and merge with existing
                    for existing in unique_sources:
                        existing_title = existing.get("data", {}).get("title", "")
                        if cls.compute_content_hash(existing_title) == content_hash:
                            if "duplicate_sources" not in existing:
                                existing["duplicate_sources"] = []
                            existing["duplicate_sources"].append(source.get("source", "unknown"))
                            break
                else:
                    seen_hashes.add(content_hash)

            # Strategy 3: Fuzzy matching
            if not is_duplicate and "title" in data:
                title = data["title"]
                for existing in unique_sources:
                    existing_title = existing.get("data", {}).get("title", "")
                    if existing_title and cls.fuzzy_similarity(title, existing_title) >= similarity_threshold:
                        is_duplicate = True
                        if "duplicate_sources" not in existing:
                            existing["duplicate_sources"] = []
                        existing["duplicate_sources"].append(source.get("source", "unknown"))
                        break

            if not is_duplicate:
                seen_identifiers.update(identifiers)
                unique_sources.append(source)

        return unique_sources


class ResearchCache:
    """
    Cache research results with rate limiting

    Features:
    - TTL-based cache expiration
    - Per-source rate limiting
    - Disk persistence (optional)
    - Cache statistics
    """

    def __init__(self, cache_dir: Optional[Path] = None, default_ttl: int = 3600):
        """
        Initialize cache

        Args:
            cache_dir: Directory for persistent cache (None = memory only)
            default_ttl: Default TTL in seconds
        """
        self.cache_dir = cache_dir
        self.default_ttl = default_ttl
        self.memory_cache: Dict[str, Dict[str, Any]] = {}
        self.rate_limits: Dict[str, List[float]] = defaultdict(list)  # domain -> timestamps

        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, url: str, params: Optional[Dict] = None) -> str:
        """Generate cache key from URL and parameters"""
        key_data = url
        if params:
            key_data += json.dumps(params, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL"""
        return urlparse(url).netloc

    def check_rate_limit(self, url: str, max_requests: int = 10,
                        window_seconds: int = 60) -> Tuple[bool, Optional[float]]:
        """
        Check if request would exceed rate limit

        Args:
            url: URL to check
            max_requests: Maximum requests per window
            window_seconds: Time window in seconds

        Returns:
            Tuple of (allowed, wait_seconds)
            allowed: True if request is allowed
            wait_seconds: Seconds to wait if not allowed (None if allowed)
        """
        domain = self._get_domain(url)
        now = time.time()

        # Clean old timestamps
        cutoff = now - window_seconds
        self.rate_limits[domain] = [ts for ts in self.rate_limits[domain] if ts > cutoff]

        # Check limit
        if len(self.rate_limits[domain]) >= max_requests:
            # Calculate wait time
            oldest = min(self.rate_limits[domain])
            wait_time = window_seconds - (now - oldest)
            return False, wait_time

        # Record this request
        self.rate_limits[domain].append(now)
        return True, None

    def get(self, url: str, params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        Get cached result

        Args:
            url: Request URL
            params: Request parameters

        Returns:
            Cached result or None if not found/expired
        """
        cache_key = self._get_cache_key(url, params)

        # Check memory cache
        if cache_key in self.memory_cache:
            entry = self.memory_cache[cache_key]
            if time.time() < entry["expires_at"]:
                logger.debug(f"Cache hit (memory): {url}")
                return entry["data"]
            else:
                # Expired
                del self.memory_cache[cache_key]

        # Check disk cache
        if self.cache_dir:
            cache_file = self.cache_dir / f"{cache_key}.json"
            if cache_file.exists():
                try:
                    with open(cache_file, 'r') as f:
                        entry = json.load(f)

                    if time.time() < entry["expires_at"]:
                        logger.debug(f"Cache hit (disk): {url}")
                        # Promote to memory cache
                        self.memory_cache[cache_key] = entry
                        return entry["data"]
                    else:
                        # Expired
                        cache_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to read cache file {cache_file}: {e}")

        logger.debug(f"Cache miss: {url}")
        return None

    def put(self, url: str, data: Any, params: Optional[Dict] = None,
           ttl: Optional[int] = None) -> None:
        """
        Store result in cache

        Args:
            url: Request URL
            data: Response data
            params: Request parameters
            ttl: Time to live in seconds (None = use default)
        """
        cache_key = self._get_cache_key(url, params)
        ttl = ttl or self.default_ttl

        entry = {
            "url": url,
            "params": params,
            "data": data,
            "cached_at": time.time(),
            "expires_at": time.time() + ttl
        }

        # Store in memory
        self.memory_cache[cache_key] = entry

        # Store on disk
        if self.cache_dir:
            cache_file = self.cache_dir / f"{cache_key}.json"
            try:
                with open(cache_file, 'w') as f:
                    json.dump(entry, f)
            except Exception as e:
                logger.warning(f"Failed to write cache file {cache_file}: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_entries = len(self.memory_cache)
        if self.cache_dir and self.cache_dir.exists():
            total_entries += len(list(self.cache_dir.glob("*.json")))

        return {
            "memory_entries": len(self.memory_cache),
            "total_entries": total_entries,
            "rate_limited_domains": len(self.rate_limits),
            "cache_dir": str(self.cache_dir) if self.cache_dir else None
        }


class ProvenanceLogger:
    """
    Log provenance metadata for research sources

    Tracks:
    - Source URL
    - Fetch timestamp
    - Content hash
    - Response headers
    - Query parameters
    """

    def __init__(self, log_file: Optional[Path] = None):
        """
        Initialize provenance logger

        Args:
            log_file: Path to provenance log file (None = memory only)
        """
        self.log_file = log_file
        self.entries: List[Dict[str, Any]] = []

        if log_file and log_file.exists():
            self._load_log()

    def _load_log(self) -> None:
        """Load existing provenance log"""
        try:
            with open(self.log_file, 'r') as f:
                self.entries = json.load(f)
            logger.info(f"Loaded {len(self.entries)} provenance entries")
        except Exception as e:
            logger.warning(f"Failed to load provenance log: {e}")
            self.entries = []

    def _save_log(self) -> None:
        """Save provenance log to disk"""
        if not self.log_file:
            return

        try:
            with open(self.log_file, 'w') as f:
                json.dump(self.entries, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save provenance log: {e}")

    def log_fetch(self, url: str, content: Any,
                 params: Optional[Dict] = None,
                 headers: Optional[Dict] = None,
                 metadata: Optional[Dict] = None) -> str:
        """
        Log a fetch operation

        Args:
            url: Source URL
            content: Fetched content
            params: Query parameters
            headers: Response headers
            metadata: Additional metadata

        Returns:
            Provenance ID (content hash)
        """
        # Compute content hash
        if isinstance(content, dict):
            content_str = json.dumps(content, sort_keys=True)
        else:
            content_str = str(content)

        content_hash = hashlib.sha256(content_str.encode()).hexdigest()

        entry = {
            "provenance_id": content_hash,
            "url": url,
            "fetch_timestamp": datetime.now().isoformat(),
            "content_hash": content_hash,
            "params": params,
            "headers": headers,
            "metadata": metadata or {},
            "domain": urlparse(url).netloc
        }

        self.entries.append(entry)
        self._save_log()

        logger.debug(f"Logged provenance: {url} -> {content_hash[:8]}")
        return content_hash

    def get_provenance(self, provenance_id: str) -> Optional[Dict[str, Any]]:
        """Get provenance entry by ID"""
        for entry in self.entries:
            if entry["provenance_id"] == provenance_id:
                return entry
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get provenance statistics"""
        domains = defaultdict(int)
        for entry in self.entries:
            domains[entry.get("domain", "unknown")] += 1

        return {
            "total_entries": len(self.entries),
            "unique_domains": len(domains),
            "top_domains": sorted(domains.items(), key=lambda x: x[1], reverse=True)[:10]
        }


class CitationExtractor:
    """
    Extract citations from sources and generate structured bibliographic records

    Supports:
    - BibTeX format
    - APA format
    - MLA format
    - Chicago format
    - JSON structured data
    """

    @staticmethod
    def extract_citation_data(source: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract citation-relevant data from source

        Args:
            source: Source result dict

        Returns:
            Dict with citation fields
        """
        data = source.get("data", {})
        citation = {
            "type": "misc",  # Default type
            "title": data.get("title", "Untitled"),
            "author": None,
            "year": None,
            "publisher": None,
            "url": source.get("url"),
            "doi": data.get("doi"),
            "access_date": datetime.now().strftime("%Y-%m-%d")
        }

        # Extract authors
        if "author" in data:
            citation["author"] = data["author"]
        elif "authors" in data:
            authors = data["authors"]
            if isinstance(authors, list):
                citation["author"] = " and ".join(authors)
            else:
                citation["author"] = authors

        # Extract year
        for date_field in ["year", "publication_date", "date", "published"]:
            if date_field in data:
                year_match = re.search(r'\d{4}', str(data[date_field]))
                if year_match:
                    citation["year"] = year_match.group()
                    break

        # Determine type
        if data.get("doi") or data.get("journal"):
            citation["type"] = "article"
        elif data.get("isbn"):
            citation["type"] = "book"
        elif "conference" in str(data).lower():
            citation["type"] = "inproceedings"

        # Additional fields
        citation["journal"] = data.get("journal")
        citation["volume"] = data.get("volume")
        citation["number"] = data.get("number")
        citation["pages"] = data.get("pages")
        citation["publisher"] = data.get("publisher")
        citation["abstract"] = data.get("abstract")

        return citation

    @staticmethod
    def to_bibtex(citation: Dict[str, Any], cite_key: Optional[str] = None) -> str:
        """
        Generate BibTeX citation

        Args:
            citation: Citation data dict
            cite_key: Citation key (auto-generated if None)

        Returns:
            BibTeX formatted string
        """
        if not cite_key:
            # Generate cite key from author + year
            author = citation.get("author", "unknown").split()[0] if citation.get("author") else "unknown"
            year = citation.get("year", "nd")
            cite_key = f"{author.lower()}{year}"

        entry_type = citation.get("type", "misc")
        bibtex = f"@{entry_type}{{{cite_key},\n"

        # Add fields
        field_map = {
            "title": "title",
            "author": "author",
            "year": "year",
            "journal": "journal",
            "volume": "volume",
            "number": "number",
            "pages": "pages",
            "publisher": "publisher",
            "doi": "doi",
            "url": "url"
        }

        for key, bibtex_key in field_map.items():
            if key in citation and citation[key]:
                value = citation[key]
                bibtex += f"  {bibtex_key} = {{{value}}},\n"

        bibtex += "}\n"
        return bibtex

    @staticmethod
    def to_apa(citation: Dict[str, Any]) -> str:
        """Generate APA format citation"""
        parts = []

        # Author (Year).
        author = citation.get("author", "Unknown Author")
        year = citation.get("year", "n.d.")
        parts.append(f"{author} ({year}).")

        # Title.
        title = citation.get("title", "Untitled")
        if citation.get("type") == "article":
            parts.append(f"{title}.")
        else:
            parts.append(f"*{title}*.")

        # Journal/Publisher
        if citation.get("journal"):
            journal_part = f"*{citation['journal']}*"
            if citation.get("volume"):
                journal_part += f", {citation['volume']}"
                if citation.get("number"):
                    journal_part += f"({citation['number']})"
            if citation.get("pages"):
                journal_part += f", {citation['pages']}"
            parts.append(journal_part + ".")
        elif citation.get("publisher"):
            parts.append(f"{citation['publisher']}.")

        # DOI or URL
        if citation.get("doi"):
            parts.append(f"https://doi.org/{citation['doi']}")
        elif citation.get("url"):
            parts.append(citation["url"])

        return " ".join(parts)

    @staticmethod
    def to_mla(citation: Dict[str, Any]) -> str:
        """Generate MLA format citation"""
        parts = []

        # Author.
        author = citation.get("author", "Unknown Author")
        parts.append(f"{author}.")

        # "Title."
        title = citation.get("title", "Untitled")
        parts.append(f'"{title}."')

        # Journal/Publisher
        if citation.get("journal"):
            journal_part = f"*{citation['journal']}*"
            if citation.get("volume"):
                journal_part += f", vol. {citation['volume']}"
            if citation.get("number"):
                journal_part += f", no. {citation['number']}"
            parts.append(journal_part + ",")

        # Year
        if citation.get("year"):
            parts.append(f"{citation['year']}.")

        # URL
        if citation.get("url"):
            parts.append(citation["url"] + ".")

        return " ".join(parts)

    @classmethod
    def extract_bibliography(cls, sources: List[Dict[str, Any]],
                           format: str = "bibtex") -> str:
        """
        Extract bibliography from sources

        Args:
            sources: List of source results
            format: Output format (bibtex, apa, mla, json)

        Returns:
            Formatted bibliography
        """
        citations = []

        for i, source in enumerate(sources):
            citation_data = cls.extract_citation_data(source)

            if format == "bibtex":
                cite_key = f"source{i+1}"
                citations.append(cls.to_bibtex(citation_data, cite_key))
            elif format == "apa":
                citations.append(cls.to_apa(citation_data))
            elif format == "mla":
                citations.append(cls.to_mla(citation_data))
            elif format == "json":
                citations.append(citation_data)

        if format == "json":
            return json.dumps(citations, indent=2)
        else:
            return "\n\n".join(citations)
