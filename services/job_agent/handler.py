"""
Job Search Agent — AWS Lambda handler.

Responsibilities
----------------
* Accept a job-search request (role, location, skills).
* Build a structured prompt and invoke Amazon Bedrock.
* Parse the model response into a list of job recommendations.
* Persist results in DynamoDB for downstream consumption.
* Return the job list to API Gateway.

Environment variables
---------------------
JOBS_TABLE       : DynamoDB table name for job results.
BEDROCK_MODEL_ID : (optional) Bedrock model identifier override.
AWS_REGION       : AWS region (injected automatically by Lambda runtime).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import sys

# Allow running locally without installing the shared package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.bedrock_client import invoke_model
from shared.dynamodb_helper import put_item, query_items
from shared.response_formatter import error, success

logger = logging.getLogger()
logger.setLevel(logging.INFO)

JOBS_TABLE = os.environ.get("JOBS_TABLE", "ai-platform-jobs")

_SYSTEM_PROMPT = (
    "You are an expert technical recruiter and career advisor. "
    "You have deep knowledge of the tech industry, salary ranges, "
    "required skills, and job-market trends. Always respond with "
    "valid JSON only."
)

_USER_PROMPT_TEMPLATE = """
Search for job opportunities matching the following criteria:
- Role: {role}
- Location: {location}
- Skills: {skills}

Return a JSON object in this exact format:
{{
  "jobs": [
    {{
      "title": "Job Title",
      "company": "Company Name",
      "location": "City, Country",
      "salary_range": "$X - $Y",
      "required_skills": ["skill1", "skill2"],
      "match_score": 85,
      "description": "Brief role description",
      "application_tips": "Tailored tip for this role"
    }}
  ],
  "market_insights": "Brief summary of current market conditions",
  "recommended_upskilling": ["skill1", "skill2"]
}}

Provide 5 realistic job listings.
"""


def _build_prompt(role: str, location: str, skills: list[str]) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        role=role,
        location=location,
        skills=", ".join(skills),
    )


def _parse_jobs(raw_text: str) -> dict[str, Any]:
    """Extract JSON from the model's text response."""
    try:
        # Strip markdown code fences if present.
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse Bedrock response as JSON: %s", exc)
        return {"jobs": [], "market_insights": raw_text, "recommended_upskilling": []}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    API Gateway proxy event handler.

    Expected query-string parameters
    ---------------------------------
    role     : Target job role (e.g. "Senior Backend Engineer")
    location : Preferred location (e.g. "Paris, France")
    skills   : Comma-separated list of skills (e.g. "Python,AWS,Docker")
    """
    try:
        params = event.get("queryStringParameters") or {}
        role = params.get("role", "Software Engineer")
        location = params.get("location", "Remote")
        skills_raw = params.get("skills", "Python,AWS")
        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]

        logger.info("Job search: role=%s location=%s skills=%s", role, location, skills)

        prompt = _build_prompt(role, location, skills)
        raw_response = invoke_model(
            prompt,
            system_prompt=_SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.5,
        )

        jobs_data = _parse_jobs(raw_response)

        # Persist to DynamoDB.
        search_id = str(uuid.uuid4())
        put_item(
            JOBS_TABLE,
            {
                "pk": "JOB_SEARCH",
                "sk": f"{datetime.now(tz=timezone.utc).isoformat()}#{search_id}",
                "search_id": search_id,
                "role": role,
                "location": location,
                "skills": skills,
                "results": jobs_data,
            },
        )

        return success(
            {
                "search_id": search_id,
                "role": role,
                "location": location,
                **jobs_data,
            }
        )

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Job agent error: %s", exc)
        return error(f"Job agent failed: {exc}")
