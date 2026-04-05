"""
Unit tests for the Daily Summary Agent.
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


SAMPLE_SUMMARY_RESULT = json.dumps({
    "date": "2024-01-15",
    "headline": "Strong demand for Python engineers; Cloud Native is top tech trend",
    "job_market_pulse": {
        "trending_roles": ["Senior Python Engineer", "Cloud Architect"],
        "hot_locations": ["Paris", "Remote"],
        "salary_insight": "Cloud roles up 15% YoY",
    },
    "cv_insights": {
        "avg_match_improvement": "30%",
        "top_ats_keywords": ["Terraform", "Kubernetes"],
        "quick_win_tip": "Add quantified achievements",
    },
    "tech_spotlight": {
        "must_learn_this_week": "Kubernetes",
        "why": "Most in-demand container tool",
        "getting_started": "Complete CKA certification",
    },
    "action_items": [
        {
            "priority": "HIGH",
            "action": "Apply to 3 cloud roles",
            "time_required": "1 hour",
            "expected_outcome": "Interview invitations",
        }
    ],
    "motivational_insight": "Your cloud skills are highly sought after — keep pushing!",
})


def _reload_summary_handler():
    for mod in list(sys.modules.keys()):
        if "summary_agent" in mod or "bedrock_client" in mod or "dynamodb_helper" in mod:
            del sys.modules[mod]
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from services.summary_agent import handler
    return handler


class TestSummaryAgentHandler:

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_successful_summary_generation(self, mock_resource, mock_client):
        """Happy path: aggregates data and returns summary."""
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": []}
        mock_resource.return_value.Table.return_value = mock_table

        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.return_value = _make_bedrock_response(SAMPLE_SUMMARY_RESULT)
        mock_client.return_value = bedrock_mock

        handler = _reload_summary_handler()
        response = handler.lambda_handler({}, {})

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "headline" in body
        assert "action_items" in body

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_bedrock_failure_returns_500(self, mock_resource, mock_client):
        """Bedrock error should bubble up as 500."""
        mock_table = MagicMock()
        mock_table.query.return_value = {"Items": []}
        mock_resource.return_value.Table.return_value = mock_table

        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.side_effect = RuntimeError("Bedrock down")
        mock_client.return_value = bedrock_mock

        handler = _reload_summary_handler()
        response = handler.lambda_handler({}, {})

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert "error" in body

    def test_parse_summary_handles_malformed_json(self):
        handler = _reload_summary_handler()
        result = handler._parse_summary("THIS IS NOT JSON")
        assert isinstance(result, dict)
        assert "headline" in result
