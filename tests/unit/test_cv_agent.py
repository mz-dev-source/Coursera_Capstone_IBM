"""
Unit tests for the CV Optimization Agent.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_bedrock_response(text: str) -> dict:
    import io
    body = json.dumps({"content": [{"text": text}]}).encode()
    return {"body": io.BytesIO(body)}


SAMPLE_CV_TEXT = """
John Doe — Software Engineer
Experience: 5 years Python, AWS Lambda, REST APIs
Education: BSc Computer Science
"""

SAMPLE_JD = """
Senior Python Developer — TechCorp Paris
Requirements: Python 3.10+, AWS, Docker, Terraform
"""

SAMPLE_CV_RESULT = json.dumps({
    "optimised_cv": "# John Doe\n\nSenior Python Engineer ...",
    "improvements": [
        {"section": "Summary", "change": "Added ATS keywords", "reason": "Improve matching"}
    ],
    "ats_keywords_added": ["Terraform", "Docker", "AWS Lambda"],
    "match_score_before": 55,
    "match_score_after": 88,
    "executive_summary": "Experienced Python engineer with strong AWS background.",
})


def _reload_cv_handler():
    for mod in list(sys.modules.keys()):
        if "cv_agent" in mod or "bedrock_client" in mod or "dynamodb_helper" in mod:
            del sys.modules[mod]
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from services.cv_agent import handler
    return handler


class TestCVAgentHandler:

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_successful_cv_optimisation(self, mock_resource, mock_client):
        """Happy path: valid body → 200 with cv_id and download_url."""
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table

        # S3 client mock — returned for the module-level `_s3 = boto3.client("s3", ...)` call
        # which happens first during module import/reload.
        s3_mock = MagicMock()
        s3_mock.generate_presigned_url.return_value = "https://s3.example.com/cv/test.md"
        # Bedrock client mock — returned for subsequent `get_bedrock_client()` calls.
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.return_value = _make_bedrock_response(SAMPLE_CV_RESULT)
        # S3 is initialised at module level (first call); Bedrock is lazy (subsequent call).
        mock_client.side_effect = [s3_mock, bedrock_mock]

        handler = _reload_cv_handler()
        event = {
            "body": json.dumps({
                "cv_text": SAMPLE_CV_TEXT,
                "job_description": SAMPLE_JD,
            })
        }

        response = handler.lambda_handler(event, {})
        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "cv_id" in body
        assert body["match_score_after"] == 88

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_missing_cv_text_returns_400(self, mock_resource, mock_client):
        """cv_text is required; absence should yield HTTP 400."""
        handler = _reload_cv_handler()
        event = {"body": json.dumps({"job_description": SAMPLE_JD})}
        response = handler.lambda_handler(event, {})
        assert response["statusCode"] == 400

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_missing_job_description_returns_400(self, mock_resource, mock_client):
        """job_description is required; absence should yield HTTP 400."""
        handler = _reload_cv_handler()
        event = {"body": json.dumps({"cv_text": SAMPLE_CV_TEXT})}
        response = handler.lambda_handler(event, {})
        assert response["statusCode"] == 400

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_empty_body_returns_400(self, mock_resource, mock_client):
        """No body should be treated as missing cv_text → 400."""
        handler = _reload_cv_handler()
        response = handler.lambda_handler({}, {})
        assert response["statusCode"] == 400

    def test_parse_cv_result_handles_malformed_json(self):
        handler = _reload_cv_handler()
        result = handler._parse_cv_result("NOT_JSON")
        assert "optimised_cv" in result
        assert result["improvements"] == []
