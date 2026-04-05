"""
HTTP response formatter for API Gateway Lambda proxy integrations.

All agents return responses through this module so error handling
and CORS headers stay consistent across the platform.
"""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from typing import Any

logger = logging.getLogger(__name__)

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def success(body: Any, *, status_code: int = HTTPStatus.OK) -> dict[str, Any]:
    """Return a 200 (or custom) JSON success response."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **_CORS_HEADERS},
        "body": json.dumps(body, default=str),
    }


def error(message: str, *, status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR) -> dict[str, Any]:
    """Return an error JSON response."""
    logger.error("Returning HTTP %s: %s", status_code, message)
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **_CORS_HEADERS},
        "body": json.dumps({"error": message}),
    }
