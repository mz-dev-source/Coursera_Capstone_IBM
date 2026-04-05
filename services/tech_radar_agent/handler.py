"""
Tech Radar Agent — AWS Lambda handler.

Responsibilities
----------------
* Accept a technology category or specific technology name.
* Invoke Amazon Bedrock to produce a Tech Radar assessment.
* Return categorised technology trends: Adopt / Trial / Assess / Hold.
* Cache results in DynamoDB with a TTL to avoid redundant Bedrock calls.

Environment variables
---------------------
TECH_RADAR_TABLE : DynamoDB table name for tech radar results.
BEDROCK_MODEL_ID : (optional) Bedrock model identifier override.
AWS_REGION       : AWS region.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.bedrock_client import invoke_model
from shared.dynamodb_helper import get_item, put_item
from shared.response_formatter import error, success

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TECH_RADAR_TABLE = os.environ.get("TECH_RADAR_TABLE", "ai-platform-tech-radar")
CACHE_TTL_HOURS = int(os.environ.get("CACHE_TTL_HOURS", "24"))

_SYSTEM_PROMPT = (
    "You are a Principal Technology Strategist with 15+ years of experience "
    "advising Fortune 500 companies on technology adoption strategies. "
    "You have deep knowledge of cloud, AI/ML, DevOps, data engineering, "
    "and emerging tech trends. Respond only with valid JSON."
)

_USER_PROMPT_TEMPLATE = """
Generate a comprehensive Tech Radar assessment for: {category}

Classify technologies into the following rings:
- ADOPT  : Technologies ready for production use; proven, low risk
- TRIAL  : Worth pursuing in a project; not production-hardened
- ASSESS : Worth exploring; keep an eye on the space
- HOLD   : Proceed with caution; declining or risky

Return a JSON object in this exact format:
{{
  "category": "{category}",
  "assessment_date": "YYYY-MM-DD",
  "rings": {{
    "adopt": [
      {{
        "name": "Technology Name",
        "description": "Why it is in Adopt",
        "use_cases": ["use case 1"],
        "learning_resources": ["Resource 1"]
      }}
    ],
    "trial": [...],
    "assess": [...],
    "hold": [...]
  }},
  "key_trends": ["trend 1", "trend 2"],
  "investment_recommendations": "Strategic paragraph on where to invest skills"
}}

Provide 3-5 technologies per ring.
"""


def _build_prompt(category: str) -> str:
    return _USER_PROMPT_TEMPLATE.format(category=category)


def _parse_radar(raw_text: str) -> dict[str, Any]:
    try:
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse tech radar response: %s", exc)
        return {"error": "Could not parse response", "raw": raw_text}


def _get_cached(category: str) -> dict[str, Any] | None:
    """Check DynamoDB for a recent cached assessment."""
    cached = get_item(TECH_RADAR_TABLE, {"pk": "TECH_RADAR", "sk": category.lower()})
    if not cached:
        return None
    cached_at = datetime.fromisoformat(cached.get("created_at", "2000-01-01T00:00:00+00:00"))
    age_hours = (datetime.now(tz=timezone.utc) - cached_at).total_seconds() / 3600
    if age_hours < CACHE_TTL_HOURS:
        logger.info("Cache hit for category=%s (age=%.1fh)", category, age_hours)
        return cached.get("radar_data")
    return None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    API Gateway proxy event handler.

    Expected query-string parameters
    ---------------------------------
    category : Technology category (e.g. "Cloud Native", "AI/ML Frameworks")
    """
    try:
        params = event.get("queryStringParameters") or {}
        category = params.get("category", "Cloud Native")

        logger.info("Tech Radar request: category=%s", category)

        # Serve from cache when available.
        cached = _get_cached(category)
        if cached:
            return success({"source": "cache", "data": cached})

        prompt = _build_prompt(category)
        raw_response = invoke_model(
            prompt,
            system_prompt=_SYSTEM_PROMPT,
            max_tokens=3000,
            temperature=0.4,
        )

        radar_data = _parse_radar(raw_response)

        # Cache the result.
        put_item(
            TECH_RADAR_TABLE,
            {
                "pk": "TECH_RADAR",
                "sk": category.lower(),
                "category": category,
                "radar_data": radar_data,
            },
        )

        return success({"source": "bedrock", "data": radar_data})

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Tech Radar agent error: %s", exc)
        return error(f"Tech Radar agent failed: {exc}")
