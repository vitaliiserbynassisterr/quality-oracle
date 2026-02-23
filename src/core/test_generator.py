"""
Auto-generate test cases from MCP server tool manifests.

Reads tool definitions (name, description, inputSchema) and generates
test cases for functional evaluation.
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def generate_test_cases(tools: List[dict]) -> Dict[str, List[dict]]:
    """
    Generate test cases from MCP server tool definitions.

    Args:
        tools: List of tool definitions with name, description, inputSchema

    Returns:
        Dict of tool_name -> list of test cases {question, expected, input_data}
    """
    test_cases: Dict[str, List[dict]] = {}

    for tool in tools:
        name = tool.get("name", "unknown")
        description = tool.get("description", "")
        schema = tool.get("inputSchema", tool.get("parameters", {}))

        cases = []

        # Happy path: use description as the test prompt
        if description:
            cases.append({
                "question": f"Use the '{name}' tool: {description}",
                "expected": f"Tool should respond with relevant output matching its purpose: {description}",
                "test_type": "happy_path",
                "input_data": _generate_sample_input(schema),
            })

        # Schema validation: check if tool handles missing required params
        required = schema.get("required", [])
        if required:
            cases.append({
                "question": f"Call '{name}' without required parameter '{required[0]}'",
                "expected": "Tool should return a clear error message about the missing required parameter",
                "test_type": "error_handling",
                "input_data": {},
            })

        # Edge case: empty string for string params
        properties = schema.get("properties", {})
        string_params = [k for k, v in properties.items() if v.get("type") == "string"]
        if string_params:
            cases.append({
                "question": f"Call '{name}' with empty string for '{string_params[0]}'",
                "expected": "Tool should handle empty input gracefully, either with a helpful error or sensible default behavior",
                "test_type": "edge_case",
                "input_data": {string_params[0]: ""},
            })

        test_cases[name] = cases
        logger.debug(f"Generated {len(cases)} test cases for tool '{name}'")

    logger.info(f"Generated {sum(len(v) for v in test_cases.values())} total test cases for {len(tools)} tools")
    return test_cases


def _generate_sample_input(schema: dict) -> dict:
    """Generate sample input data from a JSON schema."""
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    sample = {}

    for key, prop in properties.items():
        if key not in required and len(sample) >= 3:
            continue  # Only fill required + a few optional

        prop_type = prop.get("type", "string")
        if prop_type == "string":
            sample[key] = prop.get("default", prop.get("example", f"test_{key}"))
        elif prop_type == "integer":
            sample[key] = prop.get("default", 1)
        elif prop_type == "number":
            sample[key] = prop.get("default", 1.0)
        elif prop_type == "boolean":
            sample[key] = prop.get("default", True)
        elif prop_type == "array":
            sample[key] = []
        elif prop_type == "object":
            sample[key] = {}

    return sample
