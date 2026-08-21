from fastmcp import Client
from fastmcp.client.logging import LogMessage
from .logger import create_logger
import json
import random
import os
import sys
from pathlib import Path

logger = create_logger(__name__)

# Load actual config (after envsubst) for server execution
config_path = Path(__file__).parent / "mcp_server_config.json"
with open(config_path) as f:
    config = json.load(f)

# Default servers (used when ENABLED_SERVERS is empty). External-API servers
# are intentionally excluded — data comes from the local world-data server.
# Re-enable external servers explicitly via the ENABLED_SERVERS env var.
DEFAULT_SERVERS = [
    "world-data",
]

# Filter servers based on ENABLED_SERVERS environment variable
enabled_servers = os.getenv("ENABLED_SERVERS", "").strip()

if "mcpServers" in config:
    if enabled_servers:
        # Explicit mode: use exactly what's in ENABLED_SERVERS (no auto-detection)
        enabled_list = [s.strip() for s in enabled_servers.split(",")]
        enabled_set = set(enabled_list)
        logger.info(f"Using explicit ENABLED_SERVERS: {', '.join(sorted(enabled_set))}")
    else:
        # Auto mode: local-only defaults. External-API servers are never
        # auto-enabled (even if their API keys are set) — use ENABLED_SERVERS
        # to opt back in explicitly.
        enabled_set = set(DEFAULT_SERVERS)
        logger.info(
            f"Using {len(DEFAULT_SERVERS)} default local servers: "
            f"{', '.join(sorted(enabled_set))}"
        )

    # Filter config to only enabled servers
    config["mcpServers"] = {
        name: server_config
        for name, server_config in config["mcpServers"].items()
        if name in enabled_set
    }
    logger.info(f"Total enabled: {len(enabled_set)} servers")

# Process env randomization for API key load balancing. If "env" is a list, pick a random one.
if "mcpServers" in config:
    for server_name, server_config in config["mcpServers"].items():
        if "env" in server_config and isinstance(server_config["env"], list):
            # Pick a random env from the list for load balancing
            env_list = server_config["env"]
            random_env = random.choice(env_list)
            server_config["env"] = random_env
            logger.info(
                f"Randomized env for server '{server_name}': selected from {len(env_list)} options"
            )

# Local python-module servers (e.g. world-data) must run under the same
# interpreter as this app so the agent_environment package is importable.
if "mcpServers" in config:
    for server_name, server_config in config["mcpServers"].items():
        if server_config.get("command") in ("python", "python3"):
            server_config["command"] = sys.executable


async def log_handler(message: LogMessage) -> None:
    level = message.level.upper()
    data = message.data
    match level:
        case "debug":
            logger.debug(data)
        case "info":
            logger.info(data)
        case "warning":
            logger.warning(data)
        case "error":
            logger.error(data)
        case "alert":
            logger.critical(data)
        case "emergency":
            logger.critical(data)
        case "critical":
            logger.critical(data)
        case _:
            logger.info(data)


client: Client = Client(
    config,
    log_handler=log_handler,
)
