import asyncio
import contextlib
import mcp
from typing import Any, AsyncGenerator, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import mcp.types
from .mcp_client import client, config
from .cache_policy import (
    bump_generation,
    generate_cache_key,
    is_mutating_tool,
    server_of,
    should_cache_tool,
)
from .logger import create_logger
from cacheout import Cache
import json
import hashlib
import random

CACHE_TTL_HOURS = 48

logger = create_logger(__name__)

# Create cache with appropriate settings for the use case
tool_cache = Cache(
    maxsize=10000,  # Max 10000 unique requests (fits about 2000 tasks)
    ttl=CACHE_TTL_HOURS
    * 60
    * 60,  # 48 hours TTL by default (but each item will have some slight variation)
    enable_stats=True,  # Track cache performance
)

# Tool name mappings - maps old invalid names to correct names
TOOL_NAME_MAPPINGS = {
    "brave_brave_web_search": "brave-search_brave_web_search",
    "MongoDB_aggregate": "mongodb_aggregate",
    "MongoDB_collection-schema": "mongodb_collection-schema",
    "MongoDB_count": "mongodb_count",
    "MongoDB_find": "mongodb_find",
    "MongoDB_list-collections": "mongodb_list-collections",
    "MongoDB_list-databases": "mongodb_list-databases",
}

class CallToolRequest(BaseModel):
    tool_name: str
    tool_args: Dict[str, Any]
    use_cache: bool = True


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    mcp_servers = config.get("mcpServers", {})
    logger.info(
        f"Starting agent environment with {len(mcp_servers)} MCP servers: {mcp_servers.keys()}"
    )
    async with client:
        tools = await client.list_tools()
        logger.info(f"{len(tools)} tools loaded in total")
        tool_names = [tool.name for tool in tools]
        if "desktop-commander_set_config_value" in tool_names:
            await client.call_tool(
                "desktop-commander_set_config_value",
                {"key": "allowedDirectories", "value": ["/data"]},
            )
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root() -> dict[str, str]:
    """Health check endpoint."""
    return {"message": "MCP Agent Environment API"}


@app.post("/list-tools")
async def list_tools() -> list[mcp.types.Tool]:
    """List all available tools from the MCP server."""
    async with client:
        try:
            return await client.list_tools()
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to list tools: {str(e)}"
            )


@app.post("/call-tool")
async def call_tool(
    request: CallToolRequest,
) -> list[mcp.types.ContentBlock]:
    """Call a specific tool with the provided arguments."""

    mapped_tool_name = TOOL_NAME_MAPPINGS.get(request.tool_name, request.tool_name)

    # Generate cache key
    cache_key = generate_cache_key(mapped_tool_name, request.tool_args)

    # Check cache first. The cheap predicates are tested before the lookup so a
    # use_cache=False request does no cache work at all.
    if request.use_cache and should_cache_tool(mapped_tool_name):
        cached_result = tool_cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"Returning cached result for tool '{request.tool_name}'")
            return cached_result

    async with client:
        try:
            result = await client.call_tool(mapped_tool_name, request.tool_args)

            # Check for errors first (FastMCP best practice)
            if result.is_error:
                error_msg = "Unknown error"
                if result.content and isinstance(
                    result.content[0], mcp.types.TextContent
                ):
                    error_msg = result.content[0].text
                raise HTTPException(
                    status_code=500,
                    detail=f"Tool '{request.tool_name}' execution failed: {error_msg}",
                )

            content_blocks = result.content

            # A write just landed: retire every read cached against this server
            # before it. Done by bumping the generation rather than deleting
            # keys, so it is O(1) and cannot miss an entry.
            if is_mutating_tool(mapped_tool_name):
                srv = server_of(mapped_tool_name)
                gen = bump_generation(mapped_tool_name)
                logger.info(
                    "Mutating call '%s' invalidated cached reads for server '%s' "
                    "(generation %d)",
                    mapped_tool_name, srv, gen,
                )

            # Cache the successful result only for cacheable tools
            if should_cache_tool(mapped_tool_name) and cache_key is not None:
                # TTL is 70-100% of default TTL, to avoid all items expiring at the same time
                random_ttl = int(CACHE_TTL_HOURS * 60 * 60 * random.uniform(0.7, 1.0))
                tool_cache.set(cache_key, content_blocks, ttl=random_ttl)

            return content_blocks

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to call tool '{request.tool_name}': {str(e)}",
            )


@app.get("/cache-stats")
async def get_cache_stats():
    """Get cache statistics for monitoring."""
    return {
        "cache_size": len(tool_cache),
        "max_size": tool_cache.maxsize,
        "ttl_seconds": tool_cache.ttl,
    }


@app.post("/cache-clear")
async def clear_cache():
    """Clear the entire cache."""
    tool_cache.clear()
    return {"message": "Cache cleared successfully", "cache_size": len(tool_cache)}


@app.get("/enabled-servers")
async def get_enabled_servers() -> dict[str, Any]:
    """Get list of configured MCP servers with their status (OK or ERROR_NOT_ONLINE)."""
    configured = set(config.get("mcpServers", {}).keys())

    async with client:
        try:
            tools = await client.list_tools()
            # Extract unique server prefixes from tool names (format: servername_toolname).
            # With a single configured server, fastmcp does not prefix tool
            # names, so any tool at all means that server is live.
            live_servers = set()
            if len(configured) == 1 and tools:
                live_servers = set(configured)
            else:
                for tool in tools:
                    if "_" in tool.name:
                        server_name = tool.name.split("_", 1)[0]
                        live_servers.add(server_name)

            # Build status list for each configured server
            servers = [
                (name, "OK" if name in live_servers else "ERROR_NOT_ONLINE")
                for name in sorted(configured)
            ]

            return {
                "servers": servers,
                "total": len(configured),
                "online": len(live_servers),
                "offline": len(configured - live_servers),
            }
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to get server status: {str(e)}"
            )


@app.get("/health")
async def health() -> dict[str, Any]:
    """Simple health check that verifies client is also ok. Timeout is 5 seconds."""
    try:

        async def _health_check_with_client():
            async with client:
                return {
                    "status": "health_and_client_connection_ok",
                }

        return await asyncio.wait_for(_health_check_with_client(), timeout=5.0)

    except asyncio.TimeoutError:
        return {
            "status": "health_and_client_connection_timeout",
            "error": "Client connection timed out after 5 seconds",
        }
    except Exception as e:
        return {
            "status": "health_and_client_connection_health_check_failed",
            "error": str(e),
        }
