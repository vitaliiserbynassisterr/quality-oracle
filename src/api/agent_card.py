"""A2A Agent Card — Quality Oracle as a discoverable A2A agent (v0.3 spec)."""
from fastapi import APIRouter

from src.standards.a2a_extension import build_provider_extension_declaration

router = APIRouter()


@router.get("/.well-known/agent.json")
async def agent_card():
    """
    A2A v0.3-compliant Agent Card for Quality Oracle.

    Quality Oracle IS an A2A agent that can be discovered and interacted with
    by other agents using the Google A2A protocol.
    """
    return {
        "name": "Quality Oracle",
        "description": "Active competency verification for AI agents, MCP servers, and skills. "
                       "Submit any agent or MCP server for quality evaluation and receive "
                       "a verifiable quality score with W3C VC attestation.",
        "url": "https://quality-oracle.assisterr.ai",
        "version": "0.1.0",
        "provider": {
            "organization": "Assisterr",
            "url": "https://assisterr.ai",
        },
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extensions": [build_provider_extension_declaration()],
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "evaluate-quality",
                "name": "Evaluate Agent/MCP Server Quality",
                "description": "Submit an MCP server URL or agent endpoint for quality evaluation. "
                               "Returns a quality score (0-100), tier (expert/proficient/basic/failed), "
                               "and W3C Verifiable Credential attestation.",
                "tags": ["quality", "evaluation", "verification", "mcp", "agent"],
                "examples": [
                    "Evaluate the quality of mcp-server-github",
                    "Check quality score for https://example.com/mcp-server",
                    "Get quality attestation for agent-xyz",
                ],
            },
            {
                "id": "lookup-score",
                "name": "Lookup Quality Score",
                "description": "Look up the existing quality score for a previously evaluated target.",
                "tags": ["score", "lookup", "quality"],
                "examples": [
                    "What is the quality score for mcp-server-github?",
                    "Find the best MCP servers for code generation",
                ],
            },
            {
                "id": "verify-attestation",
                "name": "Verify Quality Attestation",
                "description": "Verify the validity and authenticity of a quality attestation credential.",
                "tags": ["verify", "attestation", "credential"],
                "examples": [
                    "Verify attestation urn:uuid:abc-123",
                    "Is this quality credential still valid?",
                ],
            },
        ],
    }


@router.get("/ext/evaluation/v1")
async def extension_spec():
    """Extension specification document for Quality Oracle evaluation.

    Returns the JSON-LD-style schema describing the extension's roles and parameters.
    """
    return {
        "@context": "https://quality-oracle.assisterr.ai/ext/evaluation/v1",
        "name": "Quality Oracle Evaluation Extension",
        "version": "1.0",
        "roles": ["provider", "verified_subject"],
        "params_schema": {
            "provider": {
                "evaluation_levels": "array",
                "supported_targets": "array",
                "attestation_format": "string",
            },
            "verified_subject": {
                "score": "integer(0-100)",
                "tier": "string",
                "confidence": "float",
                "last_evaluated": "string (ISO 8601)",
                "attestation_url": "string",
                "badge_url": "string",
                "verify_url": "string",
            },
        },
    }
