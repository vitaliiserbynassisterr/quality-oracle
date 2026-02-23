"""SVG badge generation for quality scores."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from src.storage.mongodb import scores_col

router = APIRouter()

BADGE_COLORS = {
    "expert": "#2ecc71",
    "proficient": "#3498db",
    "basic": "#f39c12",
    "failed": "#e74c3c",
}


def _render_badge(score: int, tier: str, style: str = "flat") -> str:
    """Render an SVG badge."""
    color = BADGE_COLORS.get(tier, "#95a5a6")
    label = "quality"
    value = f"{score}/100 {tier}"
    label_width = len(label) * 7 + 10
    value_width = len(value) * 7 + 10
    total_width = label_width + value_width

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="a">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#a)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#b)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_width / 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width / 2}" y="14">{label}</text>
    <text x="{label_width + value_width / 2}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{label_width + value_width / 2}" y="14">{value}</text>
  </g>
</svg>'''


@router.get("/badge/{target_id:path}.svg")
async def get_badge(target_id: str, style: str = "flat"):
    """Get an SVG quality badge for a target."""
    doc = await scores_col().find_one({"target_id": target_id})

    if not doc:
        svg = _render_badge(0, "unknown")
    else:
        svg = _render_badge(doc.get("current_score", 0), doc.get("tier", "failed"), style)

    return Response(content=svg, media_type="image/svg+xml")
