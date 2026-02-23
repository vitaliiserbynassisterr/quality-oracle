"""A2A Agent Card — Quality Oracle as a discoverable A2A agent."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/.well-known/agent.json")
async def agent_card():
    """
    A2A-compliant Agent Card for Quality Oracle.

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
        },
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
        "extensions": {
            "quality_oracle": {
                "version": "1.0",
                "evaluation_levels": [
                    {"level": 1, "name": "Manifest Validation", "cost": "free"},
                    {"level": 2, "name": "Functional Testing", "cost": "paid"},
                    {"level": 3, "name": "Domain Expert Testing", "cost": "premium"},
                ],
                "supported_targets": ["mcp_server", "agent", "skill"],
                "attestation_format": "W3C Verifiable Credential (UAQA)",
            },
        },
    }
