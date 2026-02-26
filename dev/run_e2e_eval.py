#!/usr/bin/env python3
"""
E2E evaluation: start mock MCP server, run full pipeline, print scores.

Usage: .venv/bin/python dev/run_e2e_eval.py
"""
import asyncio
import os
import socket
import subprocess
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

MOCK_PORT = 8099  # Avoid conflicts with Docker on 8010
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))


def start_mock_server():
    """Start mock MCP server as a subprocess with correct env."""
    env = os.environ.copy()
    env["LOG_LEVEL"] = "INFO"  # FastMCP requires uppercase

    # Run mock server from a temp dir so .env isn't auto-loaded by pydantic-settings
    proc = subprocess.Popen(
        [
            sys.executable, "-c",
            f"""
import os, sys, json
from datetime import datetime
os.chdir('/tmp')  # Avoid picking up .env
sys.path.insert(0, {PROJECT_ROOT!r})
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Mock MCP Server",
    instructions="A mock MCP server with predictable responses for Quality Oracle testing v1.0.0",
    host="0.0.0.0", port={MOCK_PORT}, log_level="INFO")

@mcp.tool()
def calculate(expression: str) -> str:
    \"\"\"Evaluate a mathematical expression and return the result.

    Args:
        expression: A mathematical expression string (e.g., "2 + 3 * 4")
    \"\"\"
    try:
        allowed = set("0123456789+-*/().% ")
        if not all(c in allowed for c in expression):
            return json.dumps({{"error": "Invalid characters in expression"}})
        result = eval(expression)
        return json.dumps({{"result": result, "expression": expression}})
    except Exception as e:
        return json.dumps({{"error": str(e)}})

@mcp.tool()
def search_docs(query: str, limit: int = 5) -> str:
    \"\"\"Search documentation for relevant articles.

    Args:
        query: Search query string
        limit: Maximum number of results to return (default: 5)
    \"\"\"
    if not query or not query.strip():
        return json.dumps({{"error": "Query cannot be empty", "results": []}})
    mock_docs = [
        {{"title": f"Guide: {{query}}", "snippet": f"Comprehensive guide about {{query}}...", "relevance": 0.95}},
        {{"title": f"Tutorial: {{query}}", "snippet": f"Step-by-step tutorial for {{query}}...", "relevance": 0.88}},
        {{"title": f"FAQ: {{query}}", "snippet": f"Frequently asked questions about {{query}}...", "relevance": 0.75}},
        {{"title": f"Reference: {{query}}", "snippet": f"API reference for {{query}}...", "relevance": 0.70}},
        {{"title": f"Examples: {{query}}", "snippet": f"Code examples for {{query}}...", "relevance": 0.65}},
    ]
    return json.dumps({{"query": query, "results": mock_docs[:limit], "total": len(mock_docs)}})

@mcp.tool()
def get_weather(city: str) -> str:
    \"\"\"Get current weather for a city.

    Args:
        city: City name (e.g., "London", "New York")
    \"\"\"
    if not city or not city.strip():
        return json.dumps({{"error": "City name cannot be empty"}})
    h = sum(ord(c) for c in city) % 100
    return json.dumps({{
        "city": city, "temperature_c": 15 + (h % 20),
        "humidity_pct": 40 + (h % 50),
        "condition": ["sunny", "cloudy", "rainy", "partly cloudy"][h % 4],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }})

@mcp.tool()
def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    \"\"\"Convert between measurement units.

    Args:
        value: The numeric value to convert
        from_unit: Source unit (e.g., "km", "miles", "celsius", "fahrenheit")
        to_unit: Target unit (e.g., "miles", "km", "fahrenheit", "celsius")
    \"\"\"
    conversions = {{
        ("km", "miles"): lambda v: v * 0.621371,
        ("miles", "km"): lambda v: v * 1.60934,
        ("celsius", "fahrenheit"): lambda v: v * 9 / 5 + 32,
        ("fahrenheit", "celsius"): lambda v: (v - 32) * 5 / 9,
        ("kg", "lbs"): lambda v: v * 2.20462,
        ("lbs", "kg"): lambda v: v * 0.453592,
        ("meters", "feet"): lambda v: v * 3.28084,
        ("feet", "meters"): lambda v: v * 0.3048,
    }}
    key = (from_unit.lower(), to_unit.lower())
    if key not in conversions:
        return json.dumps({{"error": f"Unsupported conversion: {{from_unit}} -> {{to_unit}}"}})
    result = conversions[key](value)
    return json.dumps({{
        "value": value, "from_unit": from_unit, "to_unit": to_unit,
        "result": round(result, 4),
    }})

mcp.run(transport="sse")
""",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return proc


def wait_for_server(port, timeout=15):
    """Wait until server is accepting connections."""
    print("Starting mock MCP server...", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(("localhost", port))
            s.close()
            print(" ready!")
            return True
        except (ConnectionRefusedError, OSError):
            print(".", end="", flush=True)
            time.sleep(0.5)
    print("\nFailed to start!")
    return False


async def run_evaluation():
    """Run the full e2e evaluation pipeline."""
    from src.core.mcp_client import evaluate_server
    from src.core.evaluator import Evaluator
    from src.core.llm_judge import LLMJudge

    server_url = f"http://localhost:{MOCK_PORT}/sse"

    print(f"\n{'='*70}")
    print(f"  E2E Evaluation — Mock MCP Server on port {MOCK_PORT}")
    print(f"{'='*70}\n")

    # Step 1: Run functional evaluation
    print("[1/3] Connecting to mock server and running test cases...")
    tool_responses = await evaluate_server(server_url)

    total_cases = sum(len(v) for v in tool_responses.values())
    print(f"      Executed {total_cases} test cases across {len(tool_responses)} tools\n")

    # Print raw responses
    print("[2/3] Raw tool responses:")
    print(f"{'─'*70}")
    for tool_name, responses in tool_responses.items():
        for i, resp in enumerate(responses):
            status = "ERROR" if resp.get("is_error") else "OK"
            answer = resp["answer"][:120] + "..." if len(resp["answer"]) > 120 else resp["answer"]
            print(f"  {tool_name}[{i}] ({status}, {resp['latency_ms']}ms)")
            print(f"    Q: {resp['question'][:100]}")
            print(f"    A: {answer}")
    print(f"{'─'*70}\n")

    # Step 2: Judge responses — auto-detect best available provider
    from src.config import settings

    if settings.openai_api_key:
        judge = LLMJudge(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            provider="openai",
            base_url=settings.openai_base_url,
            fallback_key=settings.deepseek_api_key or None,
            fallback_model=settings.deepseek_model,
            fallback_provider="deepseek",
            fallback2_key=settings.groq_api_key or None,
            fallback2_model=settings.groq_model,
            fallback2_provider="groq",
        )
        print("[3/3] Judging responses...")
        print("      Judge: OpenAI gpt-4o-mini (primary) + DeepSeek (fallback) + Groq (fallback2)")
    elif settings.deepseek_api_key:
        judge = LLMJudge(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            provider="deepseek",
            base_url=settings.deepseek_base_url,
            fallback_key=settings.groq_api_key or None,
            fallback_model=settings.groq_model,
            fallback_provider="groq",
        )
        print("[3/3] Judging responses...")
        print("      Judge: DeepSeek (primary) + Groq (fallback)")
    else:
        judge = LLMJudge()
        print("[3/3] Judging responses (fuzzy fallback only, no API keys)...")

    evaluator = Evaluator(judge)

    result = await evaluator.evaluate_functional(
        target_id="mock-mcp-server",
        tool_responses=tool_responses,
    )

    # Print results
    print(f"\n{'='*70}")
    print(f"  EVALUATION RESULTS")
    print(f"{'='*70}\n")

    print(f"  Overall Score : {result.overall_score}/100")
    print(f"  Tier          : {result.tier}")
    print(f"  Confidence    : {result.confidence:.2f}")
    print(f"  Duration      : {result.duration_ms}ms")
    print(f"  Questions     : {result.questions_asked} asked, {result.questions_answered} answered")

    print(f"\n  Tool Scores:")
    print(f"  {'─'*50}")
    for tool_name, scores in result.tool_scores.items():
        bar = "█" * (scores["score"] // 5) + "░" * (20 - scores["score"] // 5)
        print(f"    {tool_name:20s} {scores['score']:3d}/100  [{bar}]  ({scores['tests_passed']}/{scores['tests_total']} passed)")

    print(f"\n  Individual Judgments:")
    print(f"  {'─'*50}")
    for jr in result.judge_responses:
        score = jr["score"]
        icon = "✓" if score >= 50 else "✗"
        print(f"    {icon} {jr['tool']:20s} {score:3d}/100  [{jr.get('method', '?')}] {jr['explanation']}")

    # Per test-type breakdown
    from collections import defaultdict
    type_scores = defaultdict(list)
    for jr in result.judge_responses:
        type_scores[jr.get("test_type", "unknown")].append(jr["score"])

    if type_scores:
        print("\n  Scores by Test Type:")
        print(f"  {'─'*50}")
        for ttype, scores in sorted(type_scores.items()):
            avg = sum(scores) / len(scores)
            print(f"    {ttype:20s}  avg={avg:.0f}  n={len(scores)}")

    print(f"\n{'='*70}\n")

    return result


def main():
    os.chdir(PROJECT_ROOT)

    server_proc = start_mock_server()

    if not wait_for_server(MOCK_PORT):
        stderr = server_proc.stderr.read().decode() if server_proc.stderr else ""
        print(f"Server stderr:\n{stderr}")
        server_proc.terminate()
        sys.exit(1)

    try:
        result = asyncio.run(run_evaluation())
        return_code = 0 if result.overall_score >= 40 else 1
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return_code = 1
    finally:
        server_proc.kill()
        try:
            server_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    sys.exit(return_code)


if __name__ == "__main__":
    main()
