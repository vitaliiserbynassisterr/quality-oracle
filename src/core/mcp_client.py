"""
MCP Client wrapper for connecting to and evaluating target MCP servers.

Supports both SSE and Streamable HTTP transports with auto-detection
and fallback. Uses the official MCP SDK.
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import TextContent

logger = logging.getLogger(__name__)

# Timeouts
CONNECT_TIMEOUT = 10  # seconds
TOOL_CALL_TIMEOUT = 30  # seconds
SSE_READ_TIMEOUT = 60  # seconds


def _detect_transport(url: str) -> str:
    """Detect transport type from URL pattern.

    Returns "sse" for URLs ending in /sse, "streamable_http" otherwise.
    """
    if url.rstrip("/").endswith("/sse"):
        return "sse"
    return "streamable_http"


@asynccontextmanager
async def _connect(url: str, transport: str = "auto") -> AsyncGenerator[Tuple[str, ClientSession], None]:
    """Connect to an MCP server with transport auto-detection and fallback.

    Yields (transport_used, session) tuple.
    """
    if transport == "auto":
        transport = _detect_transport(url)

    transports_to_try = [transport]
    # Add fallback: if we try streamable_http first, fall back to SSE and vice versa
    if transport == "streamable_http":
        transports_to_try.append("sse")
    elif transport == "sse":
        transports_to_try.append("streamable_http")

    last_error = None
    for t in transports_to_try:
        try:
            if t == "sse":
                async with sse_client(
                    url=url,
                    timeout=CONNECT_TIMEOUT,
                    sse_read_timeout=SSE_READ_TIMEOUT,
                ) as (read, write):
                    async with ClientSession(read, write) as session:
                        yield t, session
                        return
            else:
                # Streamable HTTP (3-tuple: read, write, get_session_id)
                from mcp.client.streamable_http import streamablehttp_client
                async with streamablehttp_client(
                    url=url,
                    timeout=CONNECT_TIMEOUT,
                    sse_read_timeout=SSE_READ_TIMEOUT,
                ) as (read, write, _get_session_id):
                    async with ClientSession(read, write) as session:
                        yield t, session
                        return
        except Exception as e:
            last_error = e
            if len(transports_to_try) > 1 and t == transports_to_try[0]:
                logger.info(f"Transport {t} failed for {url}, trying fallback: {e}")
                continue
            raise

    if last_error:
        raise last_error


async def connect_and_list_tools(server_url: str) -> List[dict]:
    """Connect to an MCP server and list its tools."""
    logger.info(f"Connecting to MCP server: {server_url}")
    async with _connect(server_url) as (transport_used, session):
        await session.initialize()
        result = await session.list_tools()
        tools = []
        for tool in result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema if tool.inputSchema else {},
            })
        logger.info(f"Listed {len(tools)} tools from {server_url} via {transport_used}")
        return tools


async def call_tool(
    server_url: str, tool_name: str, arguments: dict
) -> dict:
    """Call a specific tool on an MCP server via a new session."""
    logger.info(f"Calling tool {tool_name} on {server_url}")
    start = time.time()
    async with _connect(server_url) as (_, session):
        await session.initialize()
        return await _call_tool_in_session(session, tool_name, arguments, start)


async def _call_tool_in_session(
    session: ClientSession,
    tool_name: str,
    arguments: dict,
    start: float,
) -> dict:
    """Call a tool within an existing session. Handles timeout and errors."""
    try:
        result = await asyncio.wait_for(
            session.call_tool(tool_name, arguments),
            timeout=TOOL_CALL_TIMEOUT,
        )
        latency_ms = int((time.time() - start) * 1000)

        # Extract text content
        text_parts = []
        for content in result.content:
            if isinstance(content, TextContent):
                text_parts.append(content.text)
            else:
                text_parts.append(str(content))

        return {
            "content": "\n".join(text_parts),
            "is_error": result.isError or False,
            "latency_ms": latency_ms,
        }
    except asyncio.TimeoutError:
        latency_ms = int((time.time() - start) * 1000)
        logger.warning(f"Tool call {tool_name} timed out after {TOOL_CALL_TIMEOUT}s")
        return {
            "content": f"Tool call timed out after {TOOL_CALL_TIMEOUT}s",
            "is_error": True,
            "latency_ms": latency_ms,
        }
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        logger.error(f"Tool call {tool_name} failed: {e}")
        return {
            "content": f"Tool call failed: {e}",
            "is_error": True,
            "latency_ms": latency_ms,
        }


async def get_server_manifest(server_url: str) -> dict:
    """
    Get the server manifest (name, version, description, tools).

    Raises ConnectionError if the server cannot be reached.
    """
    logger.info(f"Fetching manifest from {server_url}")
    try:
        async with _connect(server_url) as (transport_used, session):
            init_result = await session.initialize()

            server_info = init_result.serverInfo
            tools_result = await session.list_tools()

            tools = []
            for tool in tools_result.tools:
                tools.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema if tool.inputSchema else {},
                })

            manifest = {
                "name": server_info.name if server_info else "unknown",
                "version": server_info.version if server_info and server_info.version else "0.0.0",
                "description": "",
                "tools": tools,
                "transport": transport_used,
            }
            logger.info(
                f"Manifest: {manifest['name']} v{manifest['version']} "
                f"with {len(tools)} tools via {transport_used}"
            )
            return manifest
    except Exception as e:
        logger.error(f"Failed to connect to {server_url}: {e}")
        raise ConnectionError(f"Cannot connect to MCP server at {server_url}: {e}") from e


async def evaluate_server_streaming(
    server_url: str,
    cancel: Optional["CancellationToken"] = None,
) -> AsyncGenerator[Tuple[str, dict, dict], None]:
    """Stream tool call results as they complete.

    Yields (tool_name, test_case, response) tuples one at a time instead of
    waiting for all tool calls to finish. Caller can cancel via the token.

    Args:
        server_url: MCP server URL
        cancel: Optional CancellationToken for early termination
    """
    from src.core.test_generator import generate_test_cases

    logger.info(f"Starting streaming evaluation of {server_url}")

    async with _connect(server_url) as (transport_used, session):
        await session.initialize()
        logger.info(f"Connected to {server_url} via {transport_used} (streaming)")

        tools_result = await session.list_tools()
        tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema if t.inputSchema else {},
            }
            for t in tools_result.tools
        ]

        test_cases = generate_test_cases(tools)

        for tool_name, cases in test_cases.items():
            for case in cases:
                if cancel and cancel.is_cancelled:
                    logger.info(f"Streaming cancelled: {cancel.reason}")
                    return
                start = time.time()
                response = await _call_tool_in_session(
                    session, tool_name, case.get("input_data", {}), start
                )
                yield tool_name, case, response


async def evaluate_server(server_url: str) -> Dict[str, List[dict]]:
    """
    Full evaluation flow:
    1. Connect to server (auto-detect transport)
    2. List tools
    3. Generate test cases per tool
    4. Call each tool with test inputs
    5. Return responses for judging

    Returns dict of tool_name -> list of {question, expected, answer, latency_ms, is_error}
    """
    from src.core.test_generator import generate_test_cases

    logger.info(f"Starting full evaluation of {server_url}")

    async with _connect(server_url) as (transport_used, session):
        await session.initialize()
        logger.info(f"Connected to {server_url} via {transport_used}")

        # List tools
        tools_result = await session.list_tools()
        tools = []
        for tool in tools_result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema if tool.inputSchema else {},
            })

        # Generate test cases
        test_cases = generate_test_cases(tools)

        # Execute each test case
        results: Dict[str, List[dict]] = {}
        for tool_name, cases in test_cases.items():
            tool_results = []
            for case in cases:
                start = time.time()
                response = await _call_tool_in_session(
                    session, tool_name, case.get("input_data", {}), start
                )
                tool_results.append({
                    "question": case["question"],
                    "expected": case["expected"],
                    "answer": response["content"],
                    "latency_ms": response["latency_ms"],
                    "is_error": response["is_error"],
                    "test_type": case.get("test_type", "unknown"),
                })
            results[tool_name] = tool_results

        total_cases = sum(len(v) for v in results.values())
        logger.info(
            f"Evaluation complete: {len(tools)} tools, "
            f"{total_cases} test cases executed via {transport_used}"
        )
        return results
