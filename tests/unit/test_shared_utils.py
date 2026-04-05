"""
Unit tests for shared utilities (response_formatter, bedrock_client).
"""

from __future__ import annotations

import io
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestResponseFormatter:
    """Tests for shared/response_formatter.py"""

    def setup_method(self):
        sys.modules.pop("shared.response_formatter", None)
        from shared import response_formatter
        self.fmt = response_formatter

    def test_success_default_200(self):
        resp = self.fmt.success({"key": "value"})
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["key"] == "value"

    def test_success_custom_status(self):
        resp = self.fmt.success({"created": True}, status_code=201)
        assert resp["statusCode"] == 201

    def test_error_default_500(self):
        resp = self.fmt.error("something went wrong")
        assert resp["statusCode"] == 500
        body = json.loads(resp["body"])
        assert "error" in body
        assert "something went wrong" in body["error"]

    def test_error_custom_status(self):
        resp = self.fmt.error("bad request", status_code=400)
        assert resp["statusCode"] == 400

    def test_cors_headers_present(self):
        resp = self.fmt.success({})
        assert "Access-Control-Allow-Origin" in resp["headers"]
        assert resp["headers"]["Access-Control-Allow-Origin"] == "*"

    def test_body_serialises_non_json_types(self):
        """datetime and other non-serialisable objects should use str() fallback."""
        from datetime import datetime
        resp = self.fmt.success({"ts": datetime(2024, 1, 1)})
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert "2024-01-01" in body["ts"]


class TestBedrockClient:
    """Tests for shared/bedrock_client.py"""

    def setup_method(self):
        sys.modules.pop("shared.bedrock_client", None)

    @patch("boto3.client")
    def test_invoke_model_returns_text(self, mock_client):
        fake_text = "Here is the answer."
        body = json.dumps({"content": [{"text": fake_text}]}).encode()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.return_value = {"body": io.BytesIO(body)}
        mock_client.return_value = bedrock_mock

        from shared import bedrock_client
        result = bedrock_client.invoke_model("Hello")
        assert result == fake_text

    @patch("boto3.client")
    def test_invoke_model_uses_system_prompt(self, mock_client):
        body = json.dumps({"content": [{"text": "ok"}]}).encode()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.return_value = {"body": io.BytesIO(body)}
        mock_client.return_value = bedrock_mock

        from shared import bedrock_client
        bedrock_client.invoke_model("prompt", system_prompt="Be concise.")

        call_kwargs = bedrock_mock.invoke_model.call_args
        sent_body = json.loads(call_kwargs.kwargs["body"])
        assert sent_body["system"] == "Be concise."

    @patch("boto3.client")
    def test_invoke_model_respects_max_tokens(self, mock_client):
        body = json.dumps({"content": [{"text": "response"}]}).encode()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model.return_value = {"body": io.BytesIO(body)}
        mock_client.return_value = bedrock_mock

        from shared import bedrock_client
        bedrock_client.invoke_model("prompt", max_tokens=512)

        call_kwargs = bedrock_mock.invoke_model.call_args
        sent_body = json.loads(call_kwargs.kwargs["body"])
        assert sent_body["max_tokens"] == 512
