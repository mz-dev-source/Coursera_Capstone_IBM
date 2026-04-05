"""
CV Optimization Agent — AWS Lambda handler.

Responsibilities
----------------
* Accept a raw CV text and a target job description.
* Invoke Amazon Bedrock to generate an optimised, ATS-friendly CV.
* Store the generated CV in Amazon S3.
* Write metadata to DynamoDB.
* Return a pre-signed S3 URL and improvement summary to API Gateway.

Environment variables
---------------------
CV_TABLE         : DynamoDB table name for CV metadata.
CV_BUCKET        : S3 bucket for storing generated CVs.
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
from shared.dynamodb_helper import put_item
from shared.response_formatter import error, success

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CV_TABLE = os.environ.get("CV_TABLE", "ai-platform-cvs")
CV_BUCKET = os.environ.get("CV_BUCKET", "ai-platform-cv-storage")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
PRESIGNED_URL_EXPIRY = 3600  # 1 hour

_s3 = boto3.client("s3", region_name=AWS_REGION)

_SYSTEM_PROMPT = (
    "You are an expert career coach and technical CV writer specialising "
    "in ATS optimisation for tech roles. You improve CVs to maximise interview "
    "callbacks. Respond only with valid JSON."
)

_USER_PROMPT_TEMPLATE = """
Optimise the following CV for the target job description.

TARGET JOB DESCRIPTION:
{job_description}

CURRENT CV:
{cv_text}

Return a JSON object in this exact format:
{{
  "optimised_cv": "Full rewritten CV text (Markdown format)",
  "improvements": [
    {{
      "section": "Section name",
      "change": "What was changed",
      "reason": "Why this improves the CV"
    }}
  ],
  "ats_keywords_added": ["keyword1", "keyword2"],
  "match_score_before": 60,
  "match_score_after": 90,
  "executive_summary": "One-paragraph summary of the optimised profile"
}}
"""


def _build_prompt(cv_text: str, job_description: str) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        cv_text=cv_text,
        job_description=job_description,
    )


def _parse_cv_result(raw_text: str) -> dict[str, Any]:
    try:
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse CV response as JSON: %s", exc)
        return {
            "optimised_cv": raw_text,
            "improvements": [],
            "ats_keywords_added": [],
            "match_score_before": 0,
            "match_score_after": 0,
            "executive_summary": "",
        }


def _store_cv_in_s3(cv_text: str, cv_id: str) -> str:
    """Upload CV to S3 and return a pre-signed URL."""
    key = f"cvs/{cv_id}.md"
    _s3.put_object(
        Bucket=CV_BUCKET,
        Key=key,
        Body=cv_text.encode("utf-8"),
        ContentType="text/markdown",
        ServerSideEncryption="AES256",
    )
    url = _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": CV_BUCKET, "Key": key},
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )
    logger.info("CV stored at s3://%s/%s", CV_BUCKET, key)
    return url


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    API Gateway proxy event handler.

    Expected request body (JSON)
    ----------------------------
    cv_text         : The candidate's current CV as plain text.
    job_description : The target job description.
    """
    try:
        body = json.loads(event.get("body") or "{}")
        cv_text = body.get("cv_text", "")
        job_description = body.get("job_description", "")

        if not cv_text:
            return error("cv_text is required", status_code=400)
        if not job_description:
            return error("job_description is required", status_code=400)

        logger.info("Optimising CV (cv_len=%d, jd_len=%d)", len(cv_text), len(job_description))

        prompt = _build_prompt(cv_text, job_description)
        raw_response = invoke_model(
            prompt,
            system_prompt=_SYSTEM_PROMPT,
            max_tokens=4096,
            temperature=0.3,
        )

        cv_data = _parse_cv_result(raw_response)
        cv_id = str(uuid.uuid4())

        # Store optimised CV in S3.
        presigned_url = _store_cv_in_s3(cv_data.get("optimised_cv", ""), cv_id)

        # Persist metadata in DynamoDB.
        put_item(
            CV_TABLE,
            {
                "pk": "CV",
                "sk": f"{datetime.now(tz=timezone.utc).isoformat()}#{cv_id}",
                "cv_id": cv_id,
                "match_score_before": cv_data.get("match_score_before"),
                "match_score_after": cv_data.get("match_score_after"),
                "ats_keywords_added": cv_data.get("ats_keywords_added", []),
                "s3_key": f"cvs/{cv_id}.md",
            },
        )

        return success(
            {
                "cv_id": cv_id,
                "download_url": presigned_url,
                "match_score_before": cv_data.get("match_score_before"),
                "match_score_after": cv_data.get("match_score_after"),
                "improvements": cv_data.get("improvements", []),
                "ats_keywords_added": cv_data.get("ats_keywords_added", []),
                "executive_summary": cv_data.get("executive_summary", ""),
            }
        )

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("CV agent error: %s", exc)
        return error(f"CV agent failed: {exc}")
