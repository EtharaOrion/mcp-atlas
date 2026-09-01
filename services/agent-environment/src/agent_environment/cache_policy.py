"""What may be cached, what invalidates it, and how a cache key is built.

Split out of main.py so it can be tested without FastAPI, cacheout, or a live
MCP client. The whole policy is pure functions over tool NAMES plus one
generation counter, which is why it can be exercised in-process; main.py holds
the cache object and the HTTP route and does nothing clever with either.

WHY THIS MODULE EXISTS AT ALL
-----------------------------
The response cache is process-global with a 48h TTL and a key built only from
(tool_name, tool_args). Nothing in that key names a session or a trial, so an
entry written by one trial is served to the next. That is harmless for a
read-only reference API -- the answer depends only on the arguments -- and
wrong for anything the pipeline can write to, in two distinct ways:

  * caching a WRITE means the second identical call returns the first one's
    response and the write never happens;
  * caching a READ means a write that lands afterwards is invisible, and
    read -> write -> read returns the pre-write answer.

The three rules below exist to close both.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Dict

# Cache whitelist - only these servers will have their responses cached.
#
# TWO RULES DECIDE MEMBERSHIP, AND BOTH ARE ABOUT MUTATION.
#
# 1. A server whose state the AGENT ITSELF writes is not cacheable at all. Its
#    reads are a view of writes this pipeline just made, so a 48h cross-trial
#    entry serves trial N+1 the world trial N left behind. `filesystem` and
#    `git` were already excluded for exactly this reason; the same argument
#    applies to the sandbox, the database, the memory graph and the file tools,
#    which is why they now sit alongside them.
# 2. A server that is mostly reads but has some writes STAYS, and is made safe
#    by is_mutating_tool() below: a write is never cached, and it bumps that
#    server's generation so every read cached before it becomes unreachable.
#
# Entries left uncommented and not covered by rule 2 are read-only reference
# APIs whose answer depends only on the arguments.
CACHEABLE_SERVERS = {
    "airtable",
    "alchemy",
    # "arxiv",
    "brave-search",
    "calculator",
    # "cli-mcp-server",
    "clinicaltrialsgov-mcp-server",
    "context7",
    "ddg-search",
    # "desktop-commander",   # rule 1: reads/writes files, same class as "filesystem"
    # "e2b-server",          # rule 1: sandbox the agent mutates
    "exa",
    "fetch",
    # "filesystem",
    # "git",
    "github",
    "google-maps",
    "google-workspace",
    "lara-translate",
    # "mcp-code-executor",   # rule 1: executes code, side effects
    # "mcp-server-code-runner",  # rule 1: executes code, side effects
    # "memory",              # rule 1: knowledge graph the agent writes
    "met-museum",
    # "mongodb",             # rule 1: database the agent writes
    "national-parks",
    "notion",
    "open-library",
    "osm-mcp-server",
    "oxylabs",
    "pubmed",
    "slack",
    "twelvedata",
    "weather",
    "weather-data",
    "whois",
    "wikipedia",
}

# Action words that mean the call CHANGES something. Matched against the tool
# name's action part, on word boundaries, so `github_get_pull_request` and
# `slack_list_channels` do not match while `github_create_issue` and
# `slack_post_message` do.
#
# The error directions are not symmetric, and the list is tuned for that. A
# false positive costs one cache miss. A false negative caches a write and then
# keeps serving reads taken before it -- which is the bug this exists to stop.
# When unsure whether a verb mutates, ADD IT.
#
# Deliberately EXCLUDED, though they sound like writes: run, execute, invoke,
# start, stop, close, lock, fork, schedule. Each appears inside ordinary READ
# names on the servers that are still whitelisted -- `github_get_workflow_run`
# is the clearest -- and treating a read as a write would bump the generation on
# every call, throwing the server's whole cache away continuously. The servers
# where those words really do mean execution (e2b, the code runners) are
# excluded wholesale by rule 1, so nothing is lost by leaving them out here.
_MUTATING_VERB_RE = re.compile(
    r"(?:^|[_\-])(?:"
    r"create|update|upsert|insert|delete|remove|write|append|edit|modify|"
    r"patch|replace|rename|move|copy|duplicate|add|set|put|post|send|reply|"
    r"comment|upload|push|merge|publish|unpublish|archive|trash|restore|"
    r"revoke|grant|assign|invite|subscribe|unsubscribe"
    r")(?:$|[_\-])"
)

# server name -> generation counter. Bumped whenever a mutating call succeeds
# against that server, and mixed into every cache key for it. Reads cached
# before the write keep their old generation in the key and are simply never
# looked up again; TTL and the LRU bound reclaim them. This is what makes
# read -> write -> read return fresh data instead of the pre-write answer.
_server_generation: Dict[str, int] = {}


def server_of(tool_name: str) -> str:
    """`github_create_issue` -> `github`. The server whitelist and the
    generation counter are both keyed on this."""
    return tool_name.split("_", 1)[0]


def is_mutating_tool(tool_name: str) -> bool:
    """True when the tool name says the call changes state."""
    action = tool_name.split("_", 1)[1] if "_" in tool_name else ""
    return bool(_MUTATING_VERB_RE.search(action))


def should_cache_tool(tool_name: str) -> bool:
    """Check if tool should be cached based on server whitelist.

    A mutating tool is never cacheable, whatever its server: caching a write
    means the second identical call returns the first one's response without
    the write ever happening.
    """
    if is_mutating_tool(tool_name):
        return False
    return server_of(tool_name) in CACHEABLE_SERVERS


def bump_generation(tool_name: str) -> int:
    """Retire every read cached against this tool's server before now.

    Bumping a counter rather than deleting keys is O(1) and cannot miss an
    entry; the stale ones become unreachable and age out via TTL and the LRU
    bound. Returns the new generation so the caller can log it.
    """
    srv = server_of(tool_name)
    _server_generation[srv] = _server_generation.get(srv, 0) + 1
    return _server_generation[srv]


def generation_of(tool_name: str) -> int:
    return _server_generation.get(server_of(tool_name), 0)


def reset_generations() -> None:
    """Test helper. Nothing in the serving path calls this -- the counters are
    process-local and monotonic by design."""
    _server_generation.clear()


def generate_cache_key(tool_name: str, tool_args: dict) -> str:
    """Generate consistent cache key from tool call parameters."""
    cache_data = {
        "tool_name": tool_name,
        "tool_args": tool_args,
        "gen": generation_of(tool_name),
    }
    cache_str = json.dumps(cache_data, sort_keys=True)
    # Cache addressing only: the digest is never an authentication or
    # integrity claim, so MD5's collision weakness is not a security
    # property here. It is still a correctness one -- two colliding
    # cache_str values would serve one tool call's result to another --
    # but that needs a crafted collision in agent-supplied tool args, and
    # the blast radius is a wrong cached response inside one task run.
    # Switch to sha256 if the cache ever spans trust boundaries.
    return hashlib.md5(cache_str.encode(), usedforsecurity=False).hexdigest()
