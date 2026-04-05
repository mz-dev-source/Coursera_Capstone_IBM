"""
Unit tests for the Tech Radar Agent.
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


SAMPLE_RADAR_RESULT = json.dumps({
    "category": "Cloud Native",
    "assessment_date": "2024-01-15",
    "rings": {
        "adopt": [{"name": "Kubernetes", "description": "Production-ready", "use_cases": ["Container orchestration"], "learning_resources": ["kubernetes.io"]}],
        "trial": [{"name": "Dapr", "description": "Promising runtime", "use_cases": ["Microservices"], "learning_resources": ["dapr.io"]}],
        "assess": [{"name": "WASM", "description": "Emerging", "use_cases": ["Edge compute"], "learning_resources": ["webassembly.org"]}],
        "hold": [{"name": "Helm v2", "description": "Deprecated", "use_cases": [], "learning_resources": []}],
    },
    "key_trends": ["GitOps adoption", "FinOps"],
    "investment_recommendations": "Invest in Kubernetes and GitOps skills.",
})


def _reload_tech_radar_handler():
    for mod in list(sys.modules.keys()):
        if "tech_radar" in mod or "bedrock_client" in mod or "dynamodb_helper" in mod:
            del sys.modules[mod]
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from services.tech_radar_agent import handler
    return handler


class TestTechRadarAgentHandler:

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_successful_radar_generation(self, mock_resource, mock_client):
        """Happy path: cache miss → Bedrock call → 200 with rings."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}  # cache miss
        mock_resource.return_value.Table.return_value = mock_table

        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.return_value = _make_bedrock_response(SAMPLE_RADAR_RESULT)
        mock_client.return_value = bedrock_mock

        handler = _reload_tech_radar_handler()
        event = {"queryStringParameters": {"category": "Cloud Native"}}
        response = handler.lambda_handler(event, {})

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["source"] == "bedrock"
        assert "rings" in body["data"]

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_defaults_to_cloud_native_category(self, mock_resource, mock_client):
        """No params → default category 'Cloud Native'."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}
        mock_resource.return_value.Table.return_value = mock_table

        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.return_value = _make_bedrock_response(SAMPLE_RADAR_RESULT)
        mock_client.return_value = bedrock_mock

        handler = _reload_tech_radar_handler()
        response = handler.lambda_handler({}, {})
        assert response["statusCode"] == 200

    @patch("boto3.client")
    @patch("boto3.resource")
    def test_cache_hit_skips_bedrock(self, mock_resource, mock_client):
        """Valid cached item within TTL should NOT call Bedrock."""
        from datetime import datetime, timezone

        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {
                "pk": "TECH_RADAR",
                "sk": "cloud native",
                "category": "Cloud Native",
                "radar_data": json.loads(SAMPLE_RADAR_RESULT),
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        }
        mock_resource.return_value.Table.return_value = mock_table

        bedrock_mock = MagicMock()
        mock_client.return_value = bedrock_mock

        handler = _reload_tech_radar_handler()
        event = {"queryStringParameters": {"category": "Cloud Native"}}
        response = handler.lambda_handler(event, {})

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["source"] == "cache"
        bedrock_mock.invoke_model.assert_not_called()

    def test_parse_radar_handles_malformed_json(self):
        handler = _reload_tech_radar_handler()
        result = handler._parse_radar("GARBAGE {{{}}")
        assert "error" in result
