"""
Daily Summary Agent — AWS Lambda handler.

Responsibilities
----------------
* Aggregate outputs from Job, CV, and Tech Radar agents stored in DynamoDB.
* Pass the aggregated data to Amazon Bedrock for a coherent daily digest.
* Store the digest in DynamoDB and optionally publish to an SNS topic.
* Triggered daily by EventBridge Scheduler (can also be called via API).

Environment variables
---------------------
JOBS_TABLE       : DynamoDB table holding job search results.
CV_TABLE         : DynamoDB table holding CV metadata.
TECH_RADAR_TABLE : DynamoDB table holding tech radar results.
SUMMARY_TABLE    : DynamoDB table for storing daily summaries.
SNS_TOPIC_ARN    : (optional) SNS topic for summary delivery.
BEDROCK_MODEL_ID : (optional) Bedrock model identifier override.
AWS_REGION       : AWS region.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.bedrock_client import invoke_model
from shared.dynamodb_helper import put_item, query_items
from shared.response_formatter import error, success

logger = logging.getLogger()
logger.setLevel(logging.INFO)

JOBS_TABLE = os.environ.get("JOBS_TABLE", "ai-platform-jobs")
CV_TABLE = os.environ.get("CV_TABLE", "ai-platform-cvs")
TECH_RADAR_TABLE = os.environ.get("TECH_RADAR_TABLE", "ai-platform-tech-radar")
SUMMARY_TABLE = os.environ.get("SUMMARY_TABLE", "ai-platform-summaries")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_sns = boto3.client("sns", region_name=AWS_REGION) if SNS_TOPIC_ARN else None

_SYSTEM_PROMPT = (
    "You are a career intelligence analyst creating a concise, actionable "
    "daily briefing for a tech professional. Be specific, data-driven, and "
    "motivating. Respond only with valid JSON."
)

_USER_PROMPT_TEMPLATE = """
Create a daily career intelligence summary based on the following data:

RECENT JOB SEARCHES:
{jobs_data}

RECENT CV OPTIMISATIONS:
{cv_data}

TECH RADAR UPDATES:
{tech_radar_data}

TODAY'S DATE: {today}

Return a JSON object in this exact format:
{{
  "date": "{today}",
  "headline": "One-line summary of today's highlights",
  "job_market_pulse": {{
    "trending_roles": ["role1", "role2"],
    "hot_locations": ["location1"],
    "salary_insight": "Key salary trend"
  }},
  "cv_insights": {{
    "avg_match_improvement": "X%",
    "top_ats_keywords": ["keyword1", "keyword2"],
    "quick_win_tip": "One actionable tip"
  }},
  "tech_spotlight": {{
    "must_learn_this_week": "Technology name",
    "why": "Reason",
    "getting_started": "How to start"
  }},
  "action_items": [
    {{
      "priority": "HIGH",
      "action": "What to do",
      "time_required": "30 minutes",
      "expected_outcome": "What you will achieve"
    }}
  ],
  "motivational_insight": "Short motivating paragraph"
}}
"""


def _fetch_recent_jobs() -> str:
    items = query_items(JOBS_TABLE, "pk", "JOB_SEARCH", limit=5)
    if not items:
        return "No recent job searches."
    return json.dumps([
        {
            "role": i.get("role"),
            "location": i.get("location"),
            "jobs_count": len((i.get("results") or {}).get("jobs", [])),
        }
        for i in items
    ], default=str)


def _fetch_recent_cvs() -> str:
    items = query_items(CV_TABLE, "pk", "CV", limit=5)
    if not items:
        return "No recent CV optimisations."
    return json.dumps([
        {
            "score_before": i.get("match_score_before"),
            "score_after": i.get("match_score_after"),
            "keywords_added": i.get("ats_keywords_added", []),
        }
        for i in items
    ], default=str)


def _fetch_tech_radar() -> str:
    items = query_items(TECH_RADAR_TABLE, "pk", "TECH_RADAR", limit=3)
    if not items:
        return "No recent tech radar data."
    return json.dumps([
        {"category": i.get("category"), "key_trends": (i.get("radar_data") or {}).get("key_trends", [])}
        for i in items
    ], default=str)


def _parse_summary(raw_text: str) -> dict[str, Any]:
    try:
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse summary response: %s", exc)
        return {"headline": raw_text, "error": str(exc)}


def _publish_to_sns(summary: dict[str, Any]) -> None:
    if not _sns or not SNS_TOPIC_ARN:
        return
    try:
        _sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Daily AI Career Summary — {summary.get('date', 'Today')}",
            Message=json.dumps(summary, indent=2, default=str),
        )
        logger.info("Published summary to SNS topic %s", SNS_TOPIC_ARN)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to publish to SNS: %s", exc)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    EventBridge Scheduler or API Gateway proxy event handler.
    """
    try:
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        logger.info("Generating daily summary for %s", today)

        jobs_data = _fetch_recent_jobs()
        cv_data = _fetch_recent_cvs()
        tech_radar_data = _fetch_tech_radar()

        prompt = _USER_PROMPT_TEMPLATE.format(
            jobs_data=jobs_data,
            cv_data=cv_data,
            tech_radar_data=tech_radar_data,
            today=today,
        )

        raw_response = invoke_model(
            prompt,
            system_prompt=_SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.6,
        )

        summary_data = _parse_summary(raw_response)
        summary_id = str(uuid.uuid4())

        put_item(
            SUMMARY_TABLE,
            {
                "pk": "DAILY_SUMMARY",
                "sk": f"{today}#{summary_id}",
                "summary_id": summary_id,
                "date": today,
                "summary": summary_data,
            },
        )

        _publish_to_sns(summary_data)

        return success({"summary_id": summary_id, "date": today, **summary_data})

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Summary agent error: %s", exc)
        return error(f"Summary agent failed: {exc}")
