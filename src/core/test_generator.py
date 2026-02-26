"""
Auto-generate test cases from MCP server tool manifests.

Reads tool definitions (name, description, inputSchema) and generates
test cases for functional evaluation using semantic-aware input generation.
"""
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Semantic parameter maps — realistic values keyed by common param names
# ---------------------------------------------------------------------------
SEMANTIC_PARAM_MAP: Dict[str, List[str]] = {
    # Math / expressions
    "expression": ["2 + 3 * 4", "10 / 2", "100 - 37"],
    "formula": ["x^2 + 3x - 5", "2 * pi * r", "a^2 + b^2"],
    "equation": ["2x + 5 = 15", "x^2 - 4 = 0", "3x = 12"],
    # Search / text
    "query": ["how to install python", "machine learning tutorial", "REST API best practices"],
    "search": ["weather forecast", "python tutorial", "sorting algorithms"],
    "keyword": ["artificial intelligence", "blockchain", "cloud computing"],
    "text": ["Hello, world!", "The quick brown fox jumps over the lazy dog", "Lorem ipsum"],
    "message": ["Hello, how are you?", "Please help me with this task", "Thank you"],
    "prompt": ["Explain quantum computing in simple terms", "Write a haiku about coding"],
    "content": ["This is sample content for testing", "A short paragraph about technology"],
    "input": ["sample input data", "test input string", "example input"],
    # Location / geo
    "city": ["London", "New York", "Tokyo"],
    "location": ["San Francisco, CA", "Berlin, Germany", "Sydney, Australia"],
    "country": ["United States", "Japan", "Germany"],
    "address": ["123 Main St, Springfield", "1 Infinite Loop, Cupertino"],
    "zip": ["94105", "10001", "SW1A 1AA"],
    "zipcode": ["94105", "10001", "60601"],
    # Units / conversion
    "from_unit": ["celsius", "km", "kg"],
    "to_unit": ["fahrenheit", "miles", "lbs"],
    "unit": ["celsius", "meters", "kilograms"],
    "source_unit": ["celsius", "km", "kg"],
    "target_unit": ["fahrenheit", "miles", "lbs"],
    # Identity / user
    "name": ["John Doe", "Jane Smith", "Alice Johnson"],
    "username": ["johndoe", "janesmith", "testuser42"],
    "email": ["user@example.com", "test@mail.org", "jane@company.io"],
    "first_name": ["John", "Jane", "Alice"],
    "last_name": ["Doe", "Smith", "Johnson"],
    # Web / URLs
    "url": ["https://example.com", "https://httpbin.org/get", "https://api.github.com"],
    "link": ["https://example.com/page", "https://docs.python.org"],
    "domain": ["example.com", "github.com", "google.com"],
    # File / path
    "filename": ["report.pdf", "data.csv", "image.png"],
    "path": ["/home/user/documents", "/tmp/output.txt", "src/main.py"],
    "file": ["document.txt", "config.json", "script.py"],
    # Language
    "language": ["English", "Spanish", "French"],
    "lang": ["en", "es", "fr"],
    "locale": ["en-US", "de-DE", "ja-JP"],
    # Date / time
    "date": ["2025-01-15", "2024-06-30", "2023-12-25"],
    "time": ["14:30:00", "09:00:00", "23:59:59"],
    "timezone": ["UTC", "America/New_York", "Asia/Tokyo"],
    # Format / output
    "format": ["json", "csv", "xml"],
    "output_format": ["json", "markdown", "html"],
    # Misc
    "topic": ["artificial intelligence", "climate change", "space exploration"],
    "category": ["technology", "science", "education"],
    "description": ["A sample item for testing", "Test description"],
    "title": ["My Test Document", "Sample Report", "Example Title"],
    "id": ["abc123", "item-42", "usr_001"],
    "key": ["api_key_sample", "config_key", "setting_name"],
    "model": ["gpt-4", "claude-3", "llama-3"],
    "temperature": ["22.5", "0.7", "37.0"],
    "code": ["print('hello')", "console.log('test')", "SELECT * FROM users"],
}

SEMANTIC_NUMBER_MAP: Dict[str, List[float]] = {
    "value": [42.0, 100.0, 3.14],
    "amount": [99.99, 250.0, 10.0],
    "price": [29.99, 149.0, 9.99],
    "count": [5, 10, 25],
    "limit": [5, 10, 25],
    "offset": [0, 10, 50],
    "page": [1, 2, 5],
    "max": [100, 1000, 50],
    "min": [0, 1, -10],
    "temperature": [22.5, 0.7, 37.0],
    "timeout": [30, 60, 5],
    "retries": [3, 1, 5],
    "width": [800, 1920, 640],
    "height": [600, 1080, 480],
    "radius": [10.0, 50.0, 100.0],
    "age": [25, 30, 42],
    "quantity": [1, 5, 10],
    "score": [85.0, 92.5, 70.0],
    "weight": [75.5, 100.0, 62.3],
    "rate": [4.5, 3.8, 5.0],
    "percentage": [75.0, 50.0, 95.0],
    "latitude": [51.5074, 40.7128, 35.6762],
    "longitude": [-0.1278, -74.0060, 139.6503],
}

# ---------------------------------------------------------------------------
# Regex patterns to extract examples from parameter descriptions
# ---------------------------------------------------------------------------
_EXAMPLE_PATTERNS = [
    # e.g., '2 + 3 * 4'  or  e.g. "celsius"
    re.compile(r"""e\.g\.[\s,]*['"]([^'"]+)['"]""", re.IGNORECASE),
    # Example: "celsius"  or  example: 'hello'
    re.compile(r"""[Ee]xample:?\s*['"]([^'"]+)['"]"""),
    # such as 'hello world'  or  such as "London"
    re.compile(r"""such as\s+['"]([^'"]+)['"]""", re.IGNORECASE),
    # like 'hello world'  or  like "London"
    re.compile(r"""like\s+['"]([^'"]+)['"]""", re.IGNORECASE),
    # (e.g., 'km', 'miles')  — grab just the first one
    re.compile(r"""\(e\.g\.[\s,]*['"]([^'"]+)['"]""", re.IGNORECASE),
]


def _extract_example_from_description(description: Optional[str]) -> Optional[str]:
    """Try to extract a concrete example value from a parameter description."""
    if not description:
        return None
    for pattern in _EXAMPLE_PATTERNS:
        match = pattern.search(description)
        if match:
            return match.group(1)
    return None


def _fuzzy_match_param_name(key: str, mapping: dict) -> Optional[str]:
    """
    Match compound parameter names by suffix.

    E.g. 'search_query' matches 'query', 'target_url' matches 'url'.
    """
    # Try exact match first (already handled by caller, but just in case)
    if key in mapping:
        return key

    # Try suffix match: split on _ and check last segment(s)
    parts = key.lower().replace("-", "_").split("_")
    # Check last part
    if parts[-1] in mapping:
        return parts[-1]
    # Check last two parts joined
    if len(parts) >= 2:
        two_parts = "_".join(parts[-2:])
        if two_parts in mapping:
            return two_parts
    return None


def _generate_sample_input(schema: dict, variation: int = 0) -> dict:
    """
    Generate sample input data from a JSON schema.

    Priority chain for each parameter:
    1. Schema enum values (pick by variation index)
    2. Schema default
    3. Schema examples
    4. Extracted from description via regex
    5. Semantic map by exact param name
    6. Fuzzy suffix match
    7. Fallback: f"test_{key}"
    """
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    sample = {}

    for key, prop in properties.items():
        if key not in required and len(sample) >= 3:
            continue  # Only fill required + a few optional

        prop_type = prop.get("type", "string")
        value = _resolve_param_value(key, prop, prop_type, variation)
        sample[key] = value

    return sample


def _resolve_param_value(key: str, prop: dict, prop_type: str, variation: int):
    """Resolve a single parameter value using the priority chain."""
    # 1. Enum values
    enum_values = prop.get("enum")
    if enum_values:
        return enum_values[variation % len(enum_values)]

    # 2. Schema default
    if "default" in prop:
        return prop["default"]

    # 3. Schema examples
    examples = prop.get("examples")
    if examples:
        return examples[variation % len(examples)]

    # 4. Extract from description (only for variation=0; others fall through to
    #    semantic maps which have multiple values for variation diversity)
    if variation == 0:
        desc_example = _extract_example_from_description(prop.get("description"))
        if desc_example:
            # Try to coerce to the right type
            if prop_type in ("integer", "number"):
                try:
                    return float(desc_example) if prop_type == "number" else int(desc_example)
                except (ValueError, TypeError):
                    pass
            else:
                return desc_example

    # 5 & 6. Semantic map (exact then fuzzy)
    if prop_type == "string":
        return _resolve_string_param(key, variation)
    elif prop_type in ("integer", "number"):
        return _resolve_number_param(key, prop_type, variation)
    elif prop_type == "boolean":
        return True
    elif prop_type == "array":
        return []
    elif prop_type == "object":
        return {}

    return f"test_{key}"


def _resolve_string_param(key: str, variation: int) -> str:
    """Resolve a string parameter from semantic maps."""
    key_lower = key.lower()

    # Exact match
    if key_lower in SEMANTIC_PARAM_MAP:
        values = SEMANTIC_PARAM_MAP[key_lower]
        return values[variation % len(values)]

    # Fuzzy suffix match
    matched = _fuzzy_match_param_name(key_lower, SEMANTIC_PARAM_MAP)
    if matched:
        values = SEMANTIC_PARAM_MAP[matched]
        return values[variation % len(values)]

    # Also check number map for string-typed numeric params (e.g. temperature as string)
    if key_lower in SEMANTIC_NUMBER_MAP:
        values = SEMANTIC_NUMBER_MAP[key_lower]
        return str(values[variation % len(values)])

    matched_num = _fuzzy_match_param_name(key_lower, SEMANTIC_NUMBER_MAP)
    if matched_num:
        values = SEMANTIC_NUMBER_MAP[matched_num]
        return str(values[variation % len(values)])

    return f"test_{key}"


def _resolve_number_param(key: str, prop_type: str, variation: int):
    """Resolve a numeric parameter from semantic maps."""
    key_lower = key.lower()

    # Exact match
    if key_lower in SEMANTIC_NUMBER_MAP:
        values = SEMANTIC_NUMBER_MAP[key_lower]
        val = values[variation % len(values)]
        return int(val) if prop_type == "integer" else val

    # Fuzzy suffix match
    matched = _fuzzy_match_param_name(key_lower, SEMANTIC_NUMBER_MAP)
    if matched:
        values = SEMANTIC_NUMBER_MAP[matched]
        val = values[variation % len(values)]
        return int(val) if prop_type == "integer" else val

    # Default
    return 1 if prop_type == "integer" else 1.0


# ---------------------------------------------------------------------------
# Expected behavior generation
# ---------------------------------------------------------------------------

_TOOL_BEHAVIOR_PATTERNS = [
    # (keywords in tool name, template using input_summary)
    ({"calculate", "math", "compute", "eval"}, "Should return the computed result of {inputs}"),
    ({"search", "find", "lookup", "query"}, "Should return search results relevant to {inputs}"),
    ({"weather", "forecast"}, "Should return weather data for {inputs} including temperature"),
    ({"convert", "transform", "translate"}, "Should return the conversion result for {inputs}"),
    ({"get", "fetch", "retrieve", "read", "list"}, "Should return the requested data for {inputs}"),
    ({"create", "add", "insert", "post"}, "Should successfully create a resource with {inputs}"),
    ({"update", "edit", "modify", "patch"}, "Should successfully update the resource with {inputs}"),
    ({"delete", "remove"}, "Should successfully delete the specified resource"),
]


def _generate_expected_behavior(tool_name: str, description: str, input_data: dict) -> str:
    """Generate a descriptive expected behavior based on tool semantics and inputs."""
    # Build a readable summary of input values
    if input_data:
        parts = [f"{k}='{v}'" if isinstance(v, str) else f"{k}={v}" for k, v in input_data.items()]
        input_summary = ", ".join(parts)
    else:
        input_summary = "the provided input"

    name_lower = tool_name.lower()

    for keywords, template in _TOOL_BEHAVIOR_PATTERNS:
        if any(kw in name_lower for kw in keywords):
            return template.format(inputs=input_summary)

    # Generic fallback with actual input values for keyword overlap
    return f"Should process the input ({input_summary}) and return relevant output"


# ---------------------------------------------------------------------------
# Main test case generation
# ---------------------------------------------------------------------------

def generate_test_cases(tools: List[dict]) -> Dict[str, List[dict]]:
    """
    Generate test cases from MCP server tool definitions.

    Args:
        tools: List of tool definitions with name, description, inputSchema

    Returns:
        Dict of tool_name -> list of test cases {question, expected, input_data, test_type}
    """
    test_cases: Dict[str, List[dict]] = {}

    for tool in tools:
        name = tool.get("name", "unknown")
        description = tool.get("description", "")
        schema = tool.get("inputSchema", tool.get("parameters", {}))

        cases = []

        # --- Happy path 1: primary realistic input ---
        if description:
            input_data_0 = _generate_sample_input(schema, variation=0)
            cases.append({
                "question": f"Use the '{name}' tool: {description}",
                "expected": _generate_expected_behavior(name, description, input_data_0),
                "test_type": "happy_path",
                "input_data": input_data_0,
            })

        # --- Happy path 2: variation with different values ---
        if description:
            input_data_1 = _generate_sample_input(schema, variation=1)
            # Only add if inputs actually differ from variation 0
            input_data_0_check = _generate_sample_input(schema, variation=0)
            if input_data_1 != input_data_0_check:
                cases.append({
                    "question": f"Use the '{name}' tool with different inputs: {description}",
                    "expected": _generate_expected_behavior(name, description, input_data_1),
                    "test_type": "happy_path_variation",
                    "input_data": input_data_1,
                })

        # --- Missing required params ---
        required = schema.get("required", [])
        if required:
            cases.append({
                "question": f"Call '{name}' without required parameter '{required[0]}'",
                "expected": "Tool should return a clear error message about the missing required parameter",
                "test_type": "error_handling",
                "input_data": {},
            })

        # --- Edge case: empty string for string params ---
        properties = schema.get("properties", {})
        string_params = [k for k, v in properties.items() if v.get("type") == "string"]
        if string_params:
            cases.append({
                "question": f"Call '{name}' with empty string for '{string_params[0]}'",
                "expected": "Tool should handle empty input by returning an error message or a sensible default value",
                "test_type": "edge_case",
                "input_data": {string_params[0]: ""},
            })

        # --- Boundary: long string input ---
        if string_params:
            long_input = _generate_sample_input(schema, variation=0)
            long_input[string_params[0]] = "a" * 500
            cases.append({
                "question": f"Call '{name}' with a very long string input for '{string_params[0]}'",
                "expected": "Tool should handle oversized input by returning an error or processing it with a valid result",
                "test_type": "boundary",
                "input_data": long_input,
            })

        # --- Type coercion: string where number expected ---
        number_params = [
            k for k, v in properties.items()
            if v.get("type") in ("integer", "number")
        ]
        if number_params:
            coercion_input = _generate_sample_input(schema, variation=0)
            coercion_input[number_params[0]] = "not_a_number"
            cases.append({
                "question": f"Call '{name}' with a string '{number_params[0]}' instead of a number",
                "expected": "Tool should reject invalid type with a validation error or coerce the value to the expected type",
                "test_type": "type_coercion",
                "input_data": coercion_input,
            })

        test_cases[name] = cases
        logger.debug(f"Generated {len(cases)} test cases for tool '{name}'")

    logger.info(f"Generated {sum(len(v) for v in test_cases.values())} total test cases for {len(tools)} tools")
    return test_cases
