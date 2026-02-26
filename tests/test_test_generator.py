"""Tests for the semantic-aware test generator."""
import pytest
from src.core.test_generator import (
    _extract_example_from_description,
    _fuzzy_match_param_name,
    _generate_sample_input,
    _generate_expected_behavior,
    generate_test_cases,
    SEMANTIC_PARAM_MAP,
    SEMANTIC_NUMBER_MAP,
)


# ---------------------------------------------------------------------------
# _extract_example_from_description
# ---------------------------------------------------------------------------

class TestExtractExample:
    def test_eg_single_quotes(self):
        assert _extract_example_from_description("e.g., '2 + 3 * 4'") == "2 + 3 * 4"

    def test_eg_double_quotes(self):
        assert _extract_example_from_description('e.g. "celsius"') == "celsius"

    def test_example_colon(self):
        assert _extract_example_from_description('Example: "hello world"') == "hello world"

    def test_such_as(self):
        assert _extract_example_from_description("such as 'London'") == "London"

    def test_like_pattern(self):
        assert _extract_example_from_description("A city name like 'Tokyo'") == "Tokyo"

    def test_paren_eg(self):
        assert _extract_example_from_description("Source unit (e.g., 'km', 'miles')") == "km"

    def test_no_match(self):
        assert _extract_example_from_description("A plain description with no examples") is None

    def test_none_input(self):
        assert _extract_example_from_description(None) is None

    def test_empty_string(self):
        assert _extract_example_from_description("") is None


# ---------------------------------------------------------------------------
# _fuzzy_match_param_name
# ---------------------------------------------------------------------------

class TestFuzzyMatch:
    def test_exact_match(self):
        assert _fuzzy_match_param_name("query", SEMANTIC_PARAM_MAP) == "query"

    def test_suffix_match(self):
        assert _fuzzy_match_param_name("search_query", SEMANTIC_PARAM_MAP) == "query"

    def test_compound_suffix(self):
        assert _fuzzy_match_param_name("target_url", SEMANTIC_PARAM_MAP) == "url"

    def test_no_match(self):
        assert _fuzzy_match_param_name("xyzzy_foobar", SEMANTIC_PARAM_MAP) is None

    def test_hyphenated(self):
        # from-unit → from_unit → suffix "unit" matches
        assert _fuzzy_match_param_name("from-unit", SEMANTIC_PARAM_MAP) is not None


# ---------------------------------------------------------------------------
# _generate_sample_input
# ---------------------------------------------------------------------------

class TestGenerateSampleInput:
    def test_enum_priority(self):
        """Enum values should be picked over everything else."""
        schema = {
            "properties": {
                "color": {"type": "string", "enum": ["red", "green", "blue"]}
            },
            "required": ["color"],
        }
        result = _generate_sample_input(schema, variation=0)
        assert result["color"] == "red"
        result1 = _generate_sample_input(schema, variation=1)
        assert result1["color"] == "green"

    def test_default_priority(self):
        """Default should be used when no enum."""
        schema = {
            "properties": {
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["limit"],
        }
        result = _generate_sample_input(schema)
        assert result["limit"] == 10

    def test_description_example_priority(self):
        """Example from description regex should be used when no enum/default."""
        schema = {
            "properties": {
                "thing": {"type": "string", "description": "A thing (e.g., 'widget')"}
            },
            "required": ["thing"],
        }
        result = _generate_sample_input(schema)
        assert result["thing"] == "widget"

    def test_semantic_map(self):
        """Semantic map should kick in for known param names."""
        schema = {
            "properties": {
                "city": {"type": "string"}
            },
            "required": ["city"],
        }
        result = _generate_sample_input(schema, variation=0)
        assert result["city"] == "London"

    def test_semantic_map_variation(self):
        """Different variations should produce different values."""
        schema = {
            "properties": {
                "city": {"type": "string"}
            },
            "required": ["city"],
        }
        r0 = _generate_sample_input(schema, variation=0)
        r1 = _generate_sample_input(schema, variation=1)
        assert r0["city"] != r1["city"]

    def test_fuzzy_suffix_for_compound_name(self):
        """search_query should match 'query' in semantic map."""
        schema = {
            "properties": {
                "search_query": {"type": "string"}
            },
            "required": ["search_query"],
        }
        result = _generate_sample_input(schema)
        assert result["search_query"] in SEMANTIC_PARAM_MAP["query"]

    def test_number_semantic_map(self):
        """Numeric params should use SEMANTIC_NUMBER_MAP."""
        schema = {
            "properties": {
                "value": {"type": "number"}
            },
            "required": ["value"],
        }
        result = _generate_sample_input(schema)
        assert result["value"] in SEMANTIC_NUMBER_MAP["value"]

    def test_fallback_for_unknown(self):
        """Truly unknown params should fallback to test_ prefix."""
        schema = {
            "properties": {
                "xyzzy_blorb": {"type": "string"}
            },
            "required": ["xyzzy_blorb"],
        }
        result = _generate_sample_input(schema)
        assert result["xyzzy_blorb"] == "test_xyzzy_blorb"

    def test_boolean_param(self):
        schema = {
            "properties": {"verbose": {"type": "boolean"}},
            "required": ["verbose"],
        }
        result = _generate_sample_input(schema)
        assert result["verbose"] is True


# ---------------------------------------------------------------------------
# _generate_expected_behavior
# ---------------------------------------------------------------------------

class TestExpectedBehavior:
    def test_calculate_tool(self):
        result = _generate_expected_behavior("calculate", "Evaluate math", {"expression": "2 + 3"})
        assert "computed result" in result
        assert "2 + 3" in result

    def test_search_tool(self):
        result = _generate_expected_behavior("search_docs", "Search docs", {"query": "python"})
        assert "search results" in result
        assert "python" in result

    def test_weather_tool(self):
        result = _generate_expected_behavior("get_weather", "Get weather", {"city": "London"})
        assert "weather" in result
        assert "London" in result

    def test_convert_tool(self):
        result = _generate_expected_behavior("convert_units", "Convert", {"value": 42, "from_unit": "km"})
        assert "conversion" in result

    def test_generic_tool(self):
        result = _generate_expected_behavior("do_something", "Does stuff", {"foo": "bar"})
        assert "bar" in result


# ---------------------------------------------------------------------------
# generate_test_cases — integration
# ---------------------------------------------------------------------------

class TestGenerateTestCases:
    """Test the full generate_test_cases() with mock server tool definitions."""

    MOCK_TOOLS = [
        {
            "name": "calculate",
            "description": "Evaluate a mathematical expression and return the result.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "A mathematical expression string (e.g., '2 + 3 * 4')",
                    }
                },
                "required": ["expression"],
            },
        },
        {
            "name": "get_weather",
            "description": "Get current weather for a city.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name (e.g., 'London', 'New York')",
                    }
                },
                "required": ["city"],
            },
        },
        {
            "name": "convert_units",
            "description": "Convert between measurement units.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "number",
                        "description": "The numeric value to convert",
                    },
                    "from_unit": {
                        "type": "string",
                        "description": "Source unit (e.g., 'km', 'miles', 'celsius', 'fahrenheit')",
                    },
                    "to_unit": {
                        "type": "string",
                        "description": "Target unit (e.g., 'miles', 'km', 'fahrenheit', 'celsius')",
                    },
                },
                "required": ["value", "from_unit", "to_unit"],
            },
        },
    ]

    def test_generates_at_least_5_cases_per_tool(self):
        result = generate_test_cases(self.MOCK_TOOLS)
        for name, cases in result.items():
            assert len(cases) >= 5, f"Tool '{name}' has only {len(cases)} cases, expected >= 5"

    def test_no_test_prefix_in_happy_path_inputs(self):
        """Happy path inputs should use realistic values, not test_ prefixes."""
        result = generate_test_cases(self.MOCK_TOOLS)
        for name, cases in result.items():
            happy = [c for c in cases if c["test_type"] == "happy_path"]
            for case in happy:
                for k, v in case["input_data"].items():
                    if isinstance(v, str):
                        assert not v.startswith("test_"), (
                            f"Tool '{name}' param '{k}' has test_ prefix: '{v}'"
                        )

    def test_calculate_gets_math_expression(self):
        result = generate_test_cases(self.MOCK_TOOLS)
        calc_happy = [c for c in result["calculate"] if c["test_type"] == "happy_path"][0]
        expr = calc_happy["input_data"]["expression"]
        # Should be a real expression from description or semantic map
        assert any(op in expr for op in ["+", "-", "*", "/"]), f"Expression '{expr}' lacks math operators"

    def test_weather_gets_real_city(self):
        result = generate_test_cases(self.MOCK_TOOLS)
        weather_happy = [c for c in result["get_weather"] if c["test_type"] == "happy_path"][0]
        city = weather_happy["input_data"]["city"]
        assert city in ["London", "New York", "Tokyo"], f"Unexpected city: {city}"

    def test_convert_gets_real_units(self):
        result = generate_test_cases(self.MOCK_TOOLS)
        conv_happy = [c for c in result["convert_units"] if c["test_type"] == "happy_path"][0]
        data = conv_happy["input_data"]
        assert data["from_unit"] in ["celsius", "km", "kg"]
        assert data["to_unit"] in ["fahrenheit", "miles", "lbs"]
        assert isinstance(data["value"], (int, float))

    def test_has_type_coercion_for_numeric_tool(self):
        """convert_units has a number param, so it should get a type_coercion test."""
        result = generate_test_cases(self.MOCK_TOOLS)
        coercion = [c for c in result["convert_units"] if c["test_type"] == "type_coercion"]
        assert len(coercion) == 1

    def test_expected_behavior_includes_input_values(self):
        """Expected behavior text should reference actual input values for keyword overlap."""
        result = generate_test_cases(self.MOCK_TOOLS)
        weather_happy = [c for c in result["get_weather"] if c["test_type"] == "happy_path"][0]
        city = weather_happy["input_data"]["city"]
        assert city in weather_happy["expected"], (
            f"Expected behavior should mention city '{city}'"
        )

    def test_variation_produces_different_inputs(self):
        """The two happy path tests should have different input values."""
        result = generate_test_cases(self.MOCK_TOOLS)
        weather_cases = result["get_weather"]
        happy_paths = [c for c in weather_cases if c["test_type"] in ("happy_path", "happy_path_variation")]
        assert len(happy_paths) == 2
        assert happy_paths[0]["input_data"]["city"] != happy_paths[1]["input_data"]["city"]

    def test_expected_behavior_edge_case_signals_error(self):
        """Edge case expected text should contain 'error' keyword for fuzzy judge."""
        result = generate_test_cases(self.MOCK_TOOLS)
        for name, cases in result.items():
            for case in cases:
                if case["test_type"] in ("edge_case", "boundary", "type_coercion"):
                    assert "error" in case["expected"].lower(), (
                        f"Tool '{name}' {case['test_type']} expected text "
                        f"must contain 'error' for fuzzy judge routing"
                    )
