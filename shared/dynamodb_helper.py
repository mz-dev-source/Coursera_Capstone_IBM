"""
Shared DynamoDB helper utilities.

Wraps common read/write patterns so agents don't need to repeat
low-level boto3 boilerplate.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)


def get_table(table_name: str) -> Any:
    """Return a DynamoDB Table resource."""
    return _dynamodb.Table(table_name)


def put_item(table_name: str, item: dict[str, Any]) -> None:
    """
    Write a single item to DynamoDB, automatically adding a
    ``created_at`` timestamp if not present.
    """
    table = get_table(table_name)
    if "created_at" not in item:
        item["created_at"] = datetime.now(tz=timezone.utc).isoformat()
    table.put_item(Item=item)
    logger.info("Wrote item to %s (pk=%s)", table_name, item.get("pk") or item.get("id"))


def get_item(table_name: str, key: dict[str, Any]) -> dict[str, Any] | None:
    """Retrieve a single item by primary key. Returns None if not found."""
    table = get_table(table_name)
    response = table.get_item(Key=key)
    return response.get("Item")


def query_items(
    table_name: str,
    pk_name: str,
    pk_value: str,
    *,
    limit: int = 50,
    scan_index_forward: bool = False,
) -> list[dict[str, Any]]:
    """
    Query items by partition key, newest-first by default.

    Parameters
    ----------
    table_name:
        Target DynamoDB table.
    pk_name:
        Name of the partition key attribute.
    pk_value:
        Value of the partition key to filter on.
    limit:
        Maximum number of items to return.
    scan_index_forward:
        If False (default) items are returned in descending sort-key order.
    """
    table = get_table(table_name)
    response = table.query(
        KeyConditionExpression=Key(pk_name).eq(pk_value),
        Limit=limit,
        ScanIndexForward=scan_index_forward,
    )
    return response.get("Items", [])
