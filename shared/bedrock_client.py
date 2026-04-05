"""
Shared Amazon Bedrock client utility.

Provides a reusable wrapper around the Bedrock Runtime API so every agent
invokes the LLM through the same, well-tested interface.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

# Default model – can be overridden per-agent via environment variable.
DEFAULT_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0"
)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_retry_config = Config(
    retries={"max_attempts": 3, "mode": "adaptive"},
)


def get_bedrock_client() -> Any:
    """Return a Bedrock Runtime boto3 client (cached per Lambda container)."""
    return boto3.client(
        "bedrock-runtime",
        region_name=AWS_REGION,
        config=_retry_config,
    )


def invoke_model(
    prompt: str,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    system_prompt: str = "You are a helpful AI assistant.",
) -> str:
    """
    Invoke an Amazon Bedrock model and return the text response.

    Parameters
    ----------
    prompt:
        The user message to send to the model.
    model_id:
        The Bedrock model identifier.
    max_tokens:
        Maximum number of tokens to generate.
    temperature:
        Sampling temperature (0–1).
    system_prompt:
        System-level instruction sent before the user message.

    Returns
    -------
    str
        The model's text response.
    """
    client = get_bedrock_client()

    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        }
    )

    logger.info("Invoking Bedrock model %s (max_tokens=%s)", model_id, max_tokens)

    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=body,
    )

    result = json.loads(response["body"].read())
    text = result["content"][0]["text"]
    logger.info("Bedrock response received (%d chars)", len(text))
    return text
