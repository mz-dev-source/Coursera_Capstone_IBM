"""
Unit tests for the Job Search Agent.

All AWS service calls (Bedrock, DynamoDB) are mocked so tests run
without real AWS credentials.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build minimal mock stubs for AWS SDK modules
# ---------------------------------------------------------------------------

def _make_bedrock_response(text: str) -> dict:
    """Return a minimal Bedrock invoke_model response structure."""
    import io
    body = json.dumps({"content": [{"text": text}]}).encode()
    return {"body": io.BytesIO(body)}


SAMPLE_JOBS_JSON = json.dumps({
    "jobs": [
        {
            "title": "Senior Python Engineer",
            "company": "TechCorp",
            "location": "Paris, France",
            "salary_range": "€70k - €90k",
            "required_skills": ["Python", "AWS"],
            "match_score": 92,
            "description": "Backend role with AWS focus",
            "application_tips": "Highlight cloud experience",
        }
    ],
    "market_insights": "Strong demand for Python engineers in 2024",
    "recommended_upskilling": ["Kubernetes", "Terraform"],
})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestJobAgentHandler:
    """Tests for services/job_agent/handler.py"""

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_successful_job_search(self, mock_resource, mock_client):
        """Happy path: valid query params → 200 with jobs list."""
        # Arrange — mock DynamoDB table
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table

        # Arrange — mock Bedrock client
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.return_value = _make_bedrock_response(SAMPLE_JOBS_JSON)
        mock_client.return_value = bedrock_mock

        # Import handler AFTER patching to capture mocked boto3
        if "services.job_agent.handler" in sys.modules:
            del sys.modules["services.job_agent.handler"]
        if "shared.bedrock_client" in sys.modules:
            del sys.modules["shared.bedrock_client"]
        if "shared.dynamodb_helper" in sys.modules:
            del sys.modules["shared.dynamodb_helper"]

        sys.path.insert(0, "/home/runner/work/Coursera_Capstone_IBM/Coursera_Capstone_IBM")
        from services.job_agent import handler

        event = {
            "queryStringParameters": {
                "role": "Senior Python Engineer",
                "location": "Paris, France",
                "skills": "Python,AWS,Docker",
            }
        }

        response = handler.lambda_handler(event, {})

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "jobs" in body
        assert body["role"] == "Senior Python Engineer"

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_defaults_when_no_params(self, mock_resource, mock_client):
        """When no query params provided, defaults should be used."""
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table

        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.return_value = _make_bedrock_response(SAMPLE_JOBS_JSON)
        mock_client.return_value = bedrock_mock

        for mod in ["services.job_agent.handler", "shared.bedrock_client", "shared.dynamodb_helper"]:
            sys.modules.pop(mod, None)

        sys.path.insert(0, "/home/runner/work/Coursera_Capstone_IBM/Coursera_Capstone_IBM")
        from services.job_agent import handler

        response = handler.lambda_handler({}, {})
        assert response["statusCode"] == 200

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_bedrock_error_returns_500(self, mock_resource, mock_client):
        """If Bedrock raises, the handler should return 500."""
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table

        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.side_effect = RuntimeError("Bedrock unavailable")
        mock_client.return_value = bedrock_mock

        for mod in ["services.job_agent.handler", "shared.bedrock_client", "shared.dynamodb_helper"]:
            sys.modules.pop(mod, None)

        sys.path.insert(0, "/home/runner/work/Coursera_Capstone_IBM/Coursera_Capstone_IBM")
        from services.job_agent import handler

        response = handler.lambda_handler({"queryStringParameters": {"role": "SWE"}}, {})
        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert "error" in body

    def test_parse_jobs_handles_malformed_json(self):
        """_parse_jobs must not raise on malformed Bedrock output."""
        for mod in ["services.job_agent.handler", "shared.bedrock_client", "shared.dynamodb_helper"]:
            sys.modules.pop(mod, None)
        sys.path.insert(0, "/home/runner/work/Coursera_Capstone_IBM/Coursera_Capstone_IBM")
        from services.job_agent import handler

        result = handler._parse_jobs("This is not JSON {{{{")
        assert isinstance(result, dict)
        assert "jobs" in result
        assert result["jobs"] == []

    def test_parse_jobs_strips_markdown_fences(self):
        """_parse_jobs must strip ```json fences before parsing."""
        for mod in ["services.job_agent.handler"]:
            sys.modules.pop(mod, None)
        sys.path.insert(0, "/home/runner/work/Coursera_Capstone_IBM/Coursera_Capstone_IBM")
        from services.job_agent import handler

        wrapped = f"```json\n{SAMPLE_JOBS_JSON}\n```"
        result = handler._parse_jobs(wrapped)
        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["title"] == "Senior Python Engineer"
