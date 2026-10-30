"""Tests for the middlewares defined in main.py."""

import sys
from typing import Optional
from unittest.mock import patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

with patch.object(sys, "argv", ["main.py", "--groups", "core"]):
    import main

from src import sdk_client


def _server() -> FastMCP:
    server = FastMCP(name="test")

    async def get_header(customer_id: str) -> Optional[str]:
        """Return the login-customer-id that would be sent."""
        return sdk_client._login_customer_id.get()  # pyright: ignore[reportPrivateUsage]

    async def create_thing(customer_id: str) -> str:
        """A write tool."""
        return "created"

    async def list_metadata() -> str:
        """A tool without customer_id."""
        return "ok"

    for tool in (get_header, create_thing, list_metadata):
        server.tool(tool)
    server.add_middleware(main.ReadOnlyMiddleware())
    server.add_middleware(main.LoginCustomerIdMiddleware())
    return server


@pytest.mark.asyncio
async def test_login_customer_id_added_only_to_customer_tools() -> None:
    async with Client(_server()) as client:
        tools = {t.name: t for t in await client.list_tools()}

    assert "login_customer_id" in tools["get_header"].inputSchema["properties"]
    assert "login_customer_id" not in tools["get_header"].inputSchema.get(
        "required", []
    )
    assert "login_customer_id" not in tools["list_metadata"].inputSchema.get(
        "properties", {}
    )


@pytest.mark.asyncio
async def test_login_customer_id_has_no_default() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_header", {"customer_id": "123"})
    assert result.data is None


@pytest.mark.asyncio
async def test_login_customer_id_applies_to_that_call_only() -> None:
    async with Client(_server()) as client:
        first = await client.call_tool(
            "get_header", {"customer_id": "123", "login_customer_id": "574-925-4657"}
        )
        second = await client.call_tool("get_header", {"customer_id": "123"})
    assert first.data == "5749254657"
    assert second.data is None


@pytest.mark.asyncio
async def test_read_only_hides_and_blocks_write_tools() -> None:
    async with Client(_server()) as client:
        names = {t.name for t in await client.list_tools()}
        with pytest.raises(ToolError):
            await client.call_tool("create_thing", {"customer_id": "123"})
    assert "create_thing" not in names
