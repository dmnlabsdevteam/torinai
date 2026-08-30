#!/usr/bin/env python3
"""
Network & Web Tools
===================
Tools for HTTP requests, web scraping, and network operations

Tools:
- http_request: Make HTTP requests
- download_file: Download files from URL
- upload_file: Upload files via HTTP
- parse_html: Parse HTML content
- extract_links: Extract URLs from webpage
- check_url_status: Check if URL is accessible
- dns_lookup: DNS queries
- ping_host: Ping network host
- port_scan: Check open ports
- websocket_connect: WebSocket connections
- graphql_query: Execute GraphQL queries
- api_call: Generic REST API caller

Author: Torin AI Team
"""

import logging
import asyncio
import json
import socket
from typing import Any, Dict, List, Optional
from pathlib import Path
import aiohttp

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata


logger = logging.getLogger(__name__)


class HttpRequestTool(Tool):
    """Make HTTP requests"""

    def __init__(self):
        super().__init__()
        self.name = "http_request"
        self.description = "Make HTTP requests to external APIs or websites"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="url",
                type="string",
                description="URL to request",
                required=True
            ),
            ToolParameter(
                name="method",
                type="string",
                description="HTTP method",
                required=False,
                default="GET",
                enum=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]
            ),
            ToolParameter(
                name="headers",
                type="object",
                description="HTTP headers",
                required=False
            ),
            ToolParameter(
                name="data",
                type="object",
                description="Request body data (JSON)",
                required=False
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Request timeout in seconds",
                required=False,
                default=30,
                min_value=1,
                max_value=300
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="http_request",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.HTTP_REQUEST,
                    description="Make HTTP requests to web services"
                )
            ]
        )

    async def execute(self, url: str, method: str = "GET", headers: dict = None,
                     data: dict = None, timeout: int = 30) -> ToolResult:
        try:
            _default_headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            if headers:
                _default_headers.update(headers)
            headers = _default_headers
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    content = await response.text()

                    return ToolResult(
                        success=response.status < 400,
                        output={
                            "url": str(response.url),
                            "status": response.status,
                            "headers": dict(response.headers),
                            "content": content[:5000],  # Limit content size
                            "content_length": len(content),
                            "method": method
                        }
                    )

        except asyncio.TimeoutError:
            return ToolResult(success=False, output=None, error=f"Request timeout after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class DownloadFileTool(Tool):
    """Download files from URL"""

    def __init__(self):
        super().__init__()
        self.name = "download_file"
        self.description = "Download a file from a URL"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="url",
                type="string",
                description="URL to download from",
                required=True
            ),
            ToolParameter(
                name="destination_path",
                type="string",
                description="Local path to save file",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="download_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DOWNLOAD,
                    description="Download files from URLs"
                )
            ]
        )

    async def execute(self, url: str, destination_path: str) -> ToolResult:
        try:
            dest = Path(destination_path).expanduser().resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return ToolResult(
                            success=False,
                            output=None,
                            error=f"HTTP {response.status}: {await response.text()}"
                        )

                    with open(dest, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)

            return ToolResult(
                success=True,
                output={
                    "url": url,
                    "destination": str(dest),
                    "size_bytes": dest.stat().st_size
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class UploadFileTool(Tool):
    """Upload files via HTTP"""

    def __init__(self):
        super().__init__()
        self.name = "upload_file"
        self.description = "Upload a file via HTTP POST/PUT"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="url",
                type="string",
                description="URL to upload to",
                required=True
            ),
            ToolParameter(
                name="file_path",
                type="string",
                description="Local file path to upload",
                required=True
            ),
            ToolParameter(
                name="field_name",
                type="string",
                description="Form field name for file",
                required=False,
                default="file"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="upload_file",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.UPLOAD,
                    description="Upload files via HTTP"
                )
            ]
        )

    async def execute(self, url: str, file_path: str, field_name: str = "file") -> ToolResult:
        try:
            file = Path(file_path).expanduser().resolve()
            if not file.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {file}")

            data = aiohttp.FormData()
            data.add_field(field_name, open(file, 'rb'), filename=file.name)

            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data) as response:
                    content = await response.text()

                    return ToolResult(
                        success=response.status < 400,
                        output={
                            "url": url,
                            "file": str(file),
                            "status": response.status,
                            "response": content[:500]
                        }
                    )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ParseHTMLTool(Tool):
    """Parse HTML content"""

    def __init__(self):
        super().__init__()
        self.name = "parse_html"
        self.description = "Parse HTML and extract elements by CSS selector"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="html",
                type="string",
                description="HTML content to parse",
                required=True
            ),
            ToolParameter(
                name="selector",
                type="string",
                description="CSS selector to extract elements",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="parse_html",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.PARSE_HTML,
                    description="Parse HTML content and extract data"
                )
            ]
        )

    async def execute(self, html: str, selector: str) -> ToolResult:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, 'html.parser')
            elements = soup.select(selector)

            results = []
            for elem in elements[:100]:  # Limit to 100 elements
                results.append({
                    'tag': elem.name,
                    'text': elem.get_text(strip=True),
                    'attrs': dict(elem.attrs)
                })

            return ToolResult(
                success=True,
                output={
                    'selector': selector,
                    'count': len(elements),
                    'elements': results
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class ExtractLinksTool(Tool):
    """Extract URLs from webpage"""

    def __init__(self):
        super().__init__()
        self.name = "extract_links"
        self.description = "Extract all links from an HTML page"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="html",
                type="string",
                description="HTML content",
                required=True
            ),
            ToolParameter(
                name="base_url",
                type="string",
                description="Base URL for resolving relative links",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="extract_links",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.PARSE_HTML,
                    description="Extract URLs and links from webpages"
                )
            ]
        )

    async def execute(self, html: str, base_url: str = None) -> ToolResult:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin

            soup = BeautifulSoup(html, 'html.parser')
            links = []

            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if base_url:
                    href = urljoin(base_url, href)

                links.append({
                    'url': href,
                    'text': a_tag.get_text(strip=True)
                })

            return ToolResult(
                success=True,
                output={
                    'count': len(links),
                    'links': links[:200]  # Limit to 200 links
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class CheckURLStatusTool(Tool):
    """Check if URL is accessible"""

    def __init__(self):
        super().__init__()
        self.name = "check_url_status"
        self.description = "Check if a URL is accessible and get HTTP status"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="url",
                type="string",
                description="URL to check",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="check_url_status",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CHECK_CONNECTIVITY,
                    description="Check if URLs are accessible"
                )
            ]
        )

    async def execute(self, url: str) -> ToolResult:
        try:
            import time
            start = time.time()

            async with aiohttp.ClientSession() as session:
                async with session.head(url, allow_redirects=True) as response:
                    response_time = time.time() - start

                    return ToolResult(
                        success=True,
                        output={
                            'url': str(response.url),
                            'status': response.status,
                            'accessible': response.status < 400,
                            'response_time_ms': round(response_time * 1000, 2),
                            'final_url': str(response.url)
                        }
                    )

        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            # Network failures ARE the finding: the check ran, the URL is not
            # reachable. Narrowed from `except Exception` because that also
            # caught defects in this tool and reported them as an unreachable
            # URL -- a bug in the checker was indistinguishable from a site
            # being down.
            return ToolResult(
                success=True,
                output={
                    'url': url,
                    'accessible': False,
                    'error': str(e)
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"accessibility check itself failed: {type(e).__name__}: {e}",
            )


class DNSLookupTool(Tool):
    """DNS lookup"""

    def __init__(self):
        super().__init__()
        self.name = "dns_lookup"
        self.description = "Perform DNS lookup for a domain"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="domain",
                type="string",
                description="Domain name to lookup",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="dns_lookup",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DNS_LOOKUP,
                    description="Perform DNS lookups and queries"
                )
            ]
        )

    async def execute(self, domain: str) -> ToolResult:
        try:
            import aiodns
            resolver = aiodns.DNSResolver()

            # Get A records (IPv4)
            a_records = await resolver.query(domain, 'A')
            ipv4 = [r.host for r in a_records]

            # Try to get AAAA records (IPv6)
            try:
                aaaa_records = await resolver.query(domain, 'AAAA')
                ipv6 = [r.host for r in aaaa_records]
            except:
                ipv6 = []

            return ToolResult(
                success=True,
                output={
                    'domain': domain,
                    'ipv4_addresses': ipv4,
                    'ipv6_addresses': ipv6
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class PingHostTool(Tool):
    """Ping network host"""

    def __init__(self):
        super().__init__()
        self.name = "ping_host"
        self.description = "Ping a network host to check connectivity"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="host",
                type="string",
                description="Hostname or IP address",
                required=True
            ),
            ToolParameter(
                name="count",
                type="number",
                description="Number of ping packets",
                required=False,
                default=4,
                min_value=1,
                max_value=10
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="ping_host",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CHECK_CONNECTIVITY,
                    description="Ping network hosts to check availability"
                )
            ]
        )

    async def execute(self, host: str, count: int = 4) -> ToolResult:
        try:
            import subprocess
            import platform

            # Different ping command for different OS
            param = '-n' if platform.system().lower() == 'windows' else '-c'

            command = ['ping', param, str(count), host]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)

            return ToolResult(
                success=result.returncode == 0,
                output={
                    'host': host,
                    'reachable': result.returncode == 0,
                    'output': result.stdout
                }
            )

        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output=None, error="Ping timeout")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class PortScanTool(Tool):
    """Check open ports"""

    def __init__(self):
        super().__init__()
        self.name = "port_scan"
        self.description = "Check if specific ports are open on a host"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="host",
                type="string",
                description="Hostname or IP address",
                required=True
            ),
            ToolParameter(
                name="ports",
                type="array",
                description="List of ports to check (e.g., [80, 443, 3306])",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="port_scan",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CHECK_CONNECTIVITY,
                    description="Scan network ports for availability"
                )
            ]
        )

    async def execute(self, host: str, ports: List[int]) -> ToolResult:
        try:
            # Callers hand this array over as a string more often than not
            # ("['8099']", "80,443"). Parse it rather than iterating characters.
            if isinstance(ports, str):
                try:
                    ports = json.loads(ports)
                except ValueError:
                    ports = ports.strip("[]() ").split(",")
            if not isinstance(ports, (list, tuple)):
                ports = [ports]

            wanted, bad = [], []
            for p in ports:
                try:
                    n = int(str(p).strip().strip("'\""))
                except (TypeError, ValueError):
                    bad.append(p)
                    continue
                (wanted if 1 <= n <= 65535 else bad).append(n if 1 <= n <= 65535 else p)

            # Refuse bad input instead of scanning it. connect_ex() raises TypeError
            # on a non-int port, and reporting that as "closed" is a silent wrong
            # answer about whether a service is exposed.
            if bad:
                return ToolResult(
                    success=False, output=None,
                    error=f"not valid ports: {bad!r} — pass integers, e.g. [80, 443]")
            if not wanted:
                return ToolResult(success=False, output=None, error="no ports given")

            results = {}
            for port in wanted[:20]:  # Limit to 20 ports
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)

                try:
                    result = sock.connect_ex((host, port))
                    results[port] = result == 0  # 0 means port is open
                except OSError:
                    results[port] = False
                finally:
                    sock.close()

            open_ports = [port for port, is_open in results.items() if is_open]

            return ToolResult(
                success=True,
                output={
                    'host': host,
                    'scanned_ports': list(results.keys()),
                    'open_ports': open_ports,
                    'results': results
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class WebSocketConnectTool(Tool):
    """WebSocket connection"""

    def __init__(self):
        super().__init__()
        self.name = "websocket_connect"
        self.description = "Connect to WebSocket and send/receive messages"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="url",
                type="string",
                description="WebSocket URL (ws:// or wss://)",
                required=True
            ),
            ToolParameter(
                name="message",
                type="string",
                description="Message to send",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="websocket_connect",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.HTTP_REQUEST,
                    description="Establish WebSocket connections"
                )
            ]
        )

    async def execute(self, url: str, message: str = None) -> ToolResult:
        try:
            import websockets

            async with websockets.connect(url) as websocket:
                if message:
                    await websocket.send(message)

                # Receive response (with timeout)
                response = await asyncio.wait_for(websocket.recv(), timeout=5)

                return ToolResult(
                    success=True,
                    output={
                        'url': url,
                        'message_sent': message,
                        'response': response
                    }
                )

        except asyncio.TimeoutError:
            return ToolResult(success=False, output=None, error="WebSocket response timeout")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class GraphQLQueryTool(Tool):
    """Execute GraphQL queries"""

    def __init__(self):
        super().__init__()
        self.name = "graphql_query"
        self.description = "Execute a GraphQL query against an endpoint"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="url",
                type="string",
                description="GraphQL endpoint URL",
                required=True
            ),
            ToolParameter(
                name="query",
                type="string",
                description="GraphQL query",
                required=True
            ),
            ToolParameter(
                name="variables",
                type="object",
                description="Query variables",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="graphql_query",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.HTTP_REQUEST,
                    description="Execute GraphQL queries"
                )
            ]
        )

    async def execute(self, url: str, query: str, variables: dict = None) -> ToolResult:
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    'query': query,
                    'variables': variables or {}
                }

                async with session.post(url, json=payload) as response:
                    result = await response.json()

                    return ToolResult(
                        success='errors' not in result,
                        output={
                            'data': result.get('data'),
                            'errors': result.get('errors')
                        }
                    )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class APICallTool(Tool):
    """Generic REST API caller"""

    def __init__(self):
        super().__init__()
        self.name = "api_call"
        self.description = "Make generic REST API call with authentication"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="url",
                type="string",
                description="API endpoint URL",
                required=True
            ),
            ToolParameter(
                name="method",
                type="string",
                description="HTTP method",
                required=False,
                default="GET",
                enum=["GET", "POST", "PUT", "DELETE", "PATCH"]
            ),
            ToolParameter(
                name="auth_type",
                type="string",
                description="Authentication type",
                required=False,
                enum=["bearer", "basic", "api_key", "none"],
                default="none"
            ),
            ToolParameter(
                name="auth_value",
                type="string",
                description="Authentication token/key value",
                required=False
            ),
            ToolParameter(
                name="body",
                type="object",
                description="Request body (JSON)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="api_call",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.HTTP_REQUEST,
                    description="Make generic REST API calls"
                )
            ]
        )

    async def execute(self, url: str, method: str = "GET", auth_type: str = "none",
                     auth_value: str = None, body: dict = None) -> ToolResult:
        try:
            headers = {}

            # Add authentication
            if auth_type == "bearer" and auth_value:
                headers['Authorization'] = f'Bearer {auth_value}'
            elif auth_type == "api_key" and auth_value:
                headers['X-API-Key'] = auth_value
            elif auth_type == "basic" and auth_value:
                headers['Authorization'] = f'Basic {auth_value}'

            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=body
                ) as response:
                    try:
                        content = await response.json()
                    except:
                        content = await response.text()

                    return ToolResult(
                        success=response.status < 400,
                        output={
                            'status': response.status,
                            'data': content,
                            'headers': dict(response.headers)
                        }
                    )

        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))


class WebSearchTool(Tool):
    """
    Real web search using DuckDuckGo (no API key required).
    Supports text search, news search, and URL-only mode.
    Returns structured results: title, url, snippet.
    """

    def __init__(self):
        super().__init__()
        self.name = "web_search"
        self.description = (
            "Search the live web using DuckDuckGo. Returns ranked results with "
            "title, URL, and snippet for each hit. Use for current events, "
            "research, documentation lookup, and real-world data."
        )
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="query",
                type="string",
                description="The search query",
                required=True
            ),
            ToolParameter(
                name="max_results",
                type="number",
                description="Maximum number of results to return (1-20)",
                required=False,
                default=10,
                min_value=1,
                max_value=20
            ),
            ToolParameter(
                name="search_type",
                type="string",
                description="Type of search: 'text' (default), 'news', or 'images'",
                required=False,
                default="text",
                enum=["text", "news", "images"]
            ),
            ToolParameter(
                name="region",
                type="string",
                description="Region for results, e.g. 'us-en', 'wt-wt' (worldwide)",
                required=False,
                default="wt-wt"
            ),
            ToolParameter(
                name="time_filter",
                type="string",
                description="Limit results by age: 'd' (day), 'w' (week), 'm' (month), 'y' (year)",
                required=False,
                default=None,
                enum=["d", "w", "m", "y"]
            )
        ]

        from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata
        self.capability_profile = ToolCapabilityProfile(
            tool_name="web_search",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.WEB_SEARCH,
                    description="Search the live web and retrieve ranked results"
                ),
                CapabilityMetadata(
                    capability=Capability.HTTP_REQUEST,
                    description="Fetch live web content via search engine"
                )
            ]
        )

    async def execute(
        self,
        query: str,
        max_results: int = 10,
        search_type: str = "text",
        region: str = "wt-wt",
        time_filter: str = None
    ) -> ToolResult:
        try:
            # Run sync DDGS in a thread to avoid blocking the event loop
            import asyncio
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._do_search(query, max_results, search_type, region, time_filter)
            )

            if results is None:
                return ToolResult(success=False, output=None, error="Search returned no results")

            return ToolResult(
                success=True,
                output={
                    "query": query,
                    "search_type": search_type,
                    "result_count": len(results),
                    "results": results
                }
            )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"Web search failed: {e}")

    def _do_search(
        self,
        query: str,
        max_results: int,
        search_type: str,
        region: str,
        time_filter: str
    ) -> list:
        """Synchronous DuckDuckGo search executed in a thread pool."""
        try:
            from ddgs import DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS
            except ImportError:
                raise ImportError(
                    "Web search requires the 'ddgs' package. "
                    "Install with: pip install ddgs"
                )

        kwargs = {"max_results": max_results}
        if region:
            kwargs["region"] = region
        if time_filter:
            kwargs["timelimit"] = time_filter

        with DDGS() as ddgs:
            if search_type == "news":
                raw = list(ddgs.news(query, **kwargs))
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("body", ""),
                        "source": r.get("source", ""),
                        "published": r.get("date", "")
                    }
                    for r in raw
                ]
            elif search_type == "images":
                raw = list(ddgs.images(query, **kwargs))
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "image_url": r.get("image", ""),
                        "source": r.get("source", "")
                    }
                    for r in raw
                ]
            else:  # text (default)
                raw = list(ddgs.text(query, **kwargs))
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")
                    }
                    for r in raw
                ]


class WebFetchTool(Tool):
    """
    High-level URL reader: fetches a page with aiohttp, strips HTML to clean
    readable text (via BeautifulSoup), and returns the content plus metadata.
    No browser required — fast and lightweight for static/server-rendered pages.
    Use BrowserTool for JavaScript-heavy pages.
    """

    def __init__(self):
        super().__init__()
        self.name = "web_fetch"
        self.description = (
            "Fetch the full readable text content of any URL. Strips HTML tags, "
            "scripts, and ads — returns clean article/page text with title and metadata. "
            "Fast, no JS execution. Use browser_navigate for JS-heavy SPAs."
        )
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="url",
                type="string",
                description="URL to fetch",
                required=True
            ),
            ToolParameter(
                name="extract",
                type="string",
                description="What to extract: 'text' (default), 'links', 'images', 'all'",
                required=False,
                default="text",
                enum=["text", "links", "images", "all"]
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Request timeout in seconds",
                required=False,
                default=20,
                min_value=5,
                max_value=60
            ),
            ToolParameter(
                name="max_chars",
                type="number",
                description="Maximum characters of text to return (default 8000)",
                required=False,
                default=8000,
                min_value=500,
                max_value=50000
            )
        ]

        from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata
        self.capability_profile = ToolCapabilityProfile(
            tool_name="web_fetch",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.FETCH_PAGE,
                    description="Fetch and extract readable text from any URL"
                ),
                CapabilityMetadata(
                    capability=Capability.HTTP_REQUEST,
                    description="Retrieve web page content over HTTP"
                )
            ]
        )

    async def execute(
        self,
        url: str,
        extract: str = "text",
        timeout: int = 20,
        max_chars: int = 8000
    ) -> ToolResult:
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    allow_redirects=True
                ) as resp:
                    if resp.status >= 400:
                        return ToolResult(
                            success=False, output=None,
                            error=f"HTTP {resp.status} for {url}"
                        )
                    html = await resp.text(errors="replace")
                    final_url = str(resp.url)

            soup = BeautifulSoup(html, "lxml")

            # Remove noise elements
            for tag in soup(["script", "style", "nav", "footer", "header",
                             "aside", "noscript", "iframe", "svg"]):
                tag.decompose()

            title = soup.title.get_text(strip=True) if soup.title else ""

            result_data: dict = {"url": final_url, "title": title}

            if extract in ("text", "all"):
                # Prefer <article> or <main>, fall back to <body>
                body = soup.find("article") or soup.find("main") or soup.body
                if body:
                    text = " ".join(body.get_text(separator=" ", strip=True).split())
                else:
                    text = " ".join(soup.get_text(separator=" ", strip=True).split())
                result_data["text"] = text[:max_chars]
                result_data["char_count"] = len(text)
                result_data["truncated"] = len(text) > max_chars

            if extract in ("links", "all"):
                links = [
                    {"text": a.get_text(strip=True), "url": urljoin(final_url, a["href"])}
                    for a in soup.find_all("a", href=True)
                    if a["href"].startswith(("http", "/", "#")) is False
                    or a["href"].startswith(("http", "/"))
                ]
                result_data["links"] = links[:200]

            if extract in ("images", "all"):
                images = [
                    {"alt": img.get("alt", ""), "src": urljoin(final_url, img["src"])}
                    for img in soup.find_all("img", src=True)
                ]
                result_data["images"] = images[:100]

            return ToolResult(success=True, output=result_data)

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"web_fetch failed: {e}")


class BrowserTool(Tool):
    """
    Full headless browser powered by Playwright/Chromium.
    Executes JavaScript, handles SPAs, can click, type, scroll, screenshot.
    Use for: dynamic pages, login flows, forms, JS-rendered content.
    Falls back gracefully if Playwright is not installed.
    """

    def __init__(self):
        super().__init__()
        self.name = "browser_navigate"
        self.description = (
            "Control a real headless Chromium browser (Playwright). Navigate URLs, "
            "wait for JS to render, click elements, fill forms, take screenshots, "
            "and extract fully-rendered page content. Handles SPAs and auth flows."
        )
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="url",
                type="string",
                description="URL to navigate to",
                required=True
            ),
            ToolParameter(
                name="action",
                type="string",
                description=(
                    "Action to perform: "
                    "'get_text' (default) — return rendered text; "
                    "'screenshot' — take a screenshot (returns base64 PNG); "
                    "'get_html' — return full rendered HTML; "
                    "'click' — click element matching 'selector'; "
                    "'fill' — fill input matching 'selector' with 'value'; "
                    "'wait_and_get' — wait for 'selector' then return text"
                ),
                required=False,
                default="get_text",
                enum=["get_text", "screenshot", "get_html", "click", "fill", "wait_and_get"]
            ),
            ToolParameter(
                name="selector",
                type="string",
                description="CSS selector or text selector for click/fill/wait actions",
                required=False
            ),
            ToolParameter(
                name="value",
                type="string",
                description="Value to type into a field (for 'fill' action)",
                required=False
            ),
            ToolParameter(
                name="wait_ms",
                type="number",
                description="Milliseconds to wait after navigation for JS to settle",
                required=False,
                default=1500,
                min_value=0,
                max_value=15000
            ),
            ToolParameter(
                name="timeout",
                type="number",
                description="Page load timeout in milliseconds",
                required=False,
                default=30000,
                min_value=5000,
                max_value=120000
            ),
            ToolParameter(
                name="max_chars",
                type="number",
                description="Maximum text characters to return",
                required=False,
                default=10000,
                min_value=500,
                max_value=100000
            )
        ]

        from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata
        self.capability_profile = ToolCapabilityProfile(
            tool_name="browser_navigate",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.BROWSE_WEB,
                    description="Full headless browser control with JS execution"
                ),
                CapabilityMetadata(
                    capability=Capability.FETCH_PAGE,
                    description="Fetch fully JS-rendered page content"
                )
            ]
        )

    async def execute(
        self,
        url: str,
        action: str = "get_text",
        selector: str = None,
        value: str = None,
        wait_ms: int = 1500,
        timeout: int = 30000,
        max_chars: int = 10000
    ) -> ToolResult:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return ToolResult(
                success=False, output=None,
                error="Playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900}
                )
                page = await context.new_page()

                await page.goto(url, timeout=timeout, wait_until="domcontentloaded")

                if wait_ms > 0:
                    await page.wait_for_timeout(wait_ms)

                title = await page.title()
                final_url = page.url

                if action == "screenshot":
                    import base64
                    png_bytes = await page.screenshot(full_page=False)
                    await browser.close()
                    return ToolResult(
                        success=True,
                        output={
                            "url": final_url,
                            "title": title,
                            "screenshot_base64": base64.b64encode(png_bytes).decode(),
                            "format": "png"
                        }
                    )

                elif action == "get_html":
                    html = await page.content()
                    await browser.close()
                    return ToolResult(
                        success=True,
                        output={"url": final_url, "title": title, "html": html[:max_chars]}
                    )

                elif action == "click":
                    if not selector:
                        await browser.close()
                        return ToolResult(success=False, output=None, error="'selector' required for click action")
                    await page.click(selector, timeout=timeout)
                    await page.wait_for_timeout(wait_ms)
                    text = await page.inner_text("body")
                    await browser.close()
                    return ToolResult(
                        success=True,
                        output={"url": page.url, "title": await page.title(), "text": text[:max_chars]}
                    )

                elif action == "fill":
                    if not selector or value is None:
                        await browser.close()
                        return ToolResult(success=False, output=None, error="'selector' and 'value' required for fill action")
                    await page.fill(selector, value, timeout=timeout)
                    await browser.close()
                    return ToolResult(
                        success=True,
                        output={"url": final_url, "title": title, "filled": selector, "value": value}
                    )

                elif action == "wait_and_get":
                    if selector:
                        await page.wait_for_selector(selector, timeout=timeout)
                    text = await page.inner_text(selector or "body")
                    await browser.close()
                    return ToolResult(
                        success=True,
                        output={"url": final_url, "title": title, "text": text[:max_chars]}
                    )

                else:  # get_text (default)
                    # Strip script/style nodes then get visible text
                    await page.evaluate(
                        """() => {
                            document.querySelectorAll('script,style,nav,footer,header,aside,noscript').forEach(e => e.remove());
                        }"""
                    )
                    text = await page.inner_text("body")
                    # Collapse whitespace
                    text = " ".join(text.split())
                    await browser.close()
                    return ToolResult(
                        success=True,
                        output={
                            "url": final_url,
                            "title": title,
                            "text": text[:max_chars],
                            "char_count": len(text),
                            "truncated": len(text) > max_chars
                        }
                    )

        except Exception as e:
            return ToolResult(success=False, output=None, error=f"browser_navigate failed: {e}")
