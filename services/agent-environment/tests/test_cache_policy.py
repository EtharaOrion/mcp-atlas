"""The response cache's policy: what may be cached, and what retires it.

These are the rules that stop one trial's tool responses being served to the
next. They are asserted on REAL tool names rather than invented ones, because
the whole policy is a set of string tests and a made-up name proves nothing
about the servers actually wired into mcp_server_config.json.

The two error directions are not symmetric, and the tests are split to match:

  * a read misclassified as a write costs a cache miss and, worse, bumps the
    generation on every call so the server's cache is thrown away continuously;
  * a write misclassified as a read is the bug this policy exists to stop -- the
    write is served from cache and never happens, and reads taken before it keep
    being returned afterwards.

Imports cache_policy directly, so this runs anywhere pytest does. main.py needs
FastAPI, cacheout and a live MCP client; the policy needs none of them, which is
why it is a separate module.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_environment import cache_policy as cp  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_generations():
    cp.reset_generations()
    yield
    cp.reset_generations()


# Ordinary reads on servers that are still whitelisted. Every one of these must
# stay cacheable -- the point of the policy is to keep the savings, not to
# switch caching off.
READS = [
    "github_get_workflow_run",       # the trap: ends in "run", is a read
    "github_list_workflow_runs",
    "github_get_file_contents",
    "github_search_code",
    "github_get_pull_request",
    "slack_list_channels",
    "airtable_list_records",
    "airtable_search_records",
    "notion_API-retrieve-a-page",
    "brave-search_brave_web_search",
    "exa_web_search_exa",
    "context7_get-library-docs",
    "national-parks_find_parks",
    "weather_get_forecast",
    "pubmed_search_pubmed",
    "wikipedia_get_article",
]

# Writes on those same servers. None may be cached, and each must retire the
# reads cached against its server.
WRITES = [
    "github_create_issue",
    "github_update_issue",
    "github_add_issue_comment",
    "github_push_files",
    "github_merge_pull_request",
    "github_create_or_update_file",
    "slack_post_message",
    "airtable_create_record",
    "airtable_update_records",
    "airtable_delete_records",
    "notion_API-patch-page",
    "notion_API-post-page",
    "google-workspace_send_gmail_message",
]

# Rule 1: the agent writes these worlds itself, so even their READS are a view
# of writes this pipeline just made and must never cross a trial boundary.
AGENT_STATE_TOOLS = [
    "mongodb_find",
    "mongodb_aggregate",
    "memory_read_graph",
    "memory_search_nodes",
    "desktop-commander_read_file",
    "e2b-server_run_code",
    "mcp-code-executor_execute_code",
    "mcp-server-code-runner_run-code",
    "filesystem_read_file",
    "git_status",
]


@pytest.mark.parametrize("tool", READS)
def test_reads_are_not_mistaken_for_writes(tool):
    """A read that bumps the generation would discard the server's cache on
    every call -- the caching would still be correct and completely useless."""
    assert not cp.is_mutating_tool(tool)


@pytest.mark.parametrize("tool", READS)
def test_reads_stay_cacheable(tool):
    assert cp.should_cache_tool(tool)


@pytest.mark.parametrize("tool", WRITES)
def test_writes_are_detected(tool):
    assert cp.is_mutating_tool(tool)


@pytest.mark.parametrize("tool", WRITES)
def test_writes_are_never_cached(tool):
    """Caching a write means the second identical call returns the first one's
    response and the write never reaches the server."""
    assert not cp.should_cache_tool(tool)


@pytest.mark.parametrize("tool", AGENT_STATE_TOOLS)
def test_agent_owned_state_is_never_cached(tool):
    assert not cp.should_cache_tool(tool)


def test_write_retires_reads_on_the_same_server():
    """read -> write -> read must not return the pre-write answer."""
    args = {"path": "README.md"}
    before = cp.generate_cache_key("github_get_file_contents", args)
    cp.bump_generation("github_create_or_update_file")
    after = cp.generate_cache_key("github_get_file_contents", args)
    assert before != after


def test_write_does_not_touch_other_servers():
    """Invalidation is per-server. A GitHub write must not throw away Slack's
    cache -- that would make one busy server degrade every other one."""
    before = cp.generate_cache_key("slack_list_channels", {})
    cp.bump_generation("github_create_issue")
    assert cp.generate_cache_key("slack_list_channels", {}) == before


def test_generation_is_monotonic_per_server():
    assert cp.generation_of("github_get_file_contents") == 0
    cp.bump_generation("github_create_issue")
    cp.bump_generation("github_update_issue")
    assert cp.generation_of("github_get_file_contents") == 2
    assert cp.generation_of("slack_list_channels") == 0


def test_cache_key_separates_tools_and_arguments():
    k = cp.generate_cache_key
    assert k("github_get_file_contents", {"path": "a"}) != k("github_get_file_contents", {"path": "b"})
    assert k("github_get_file_contents", {}) != k("github_search_code", {})
    # Argument order must not change the key, or every reordering is a miss.
    assert k("x_get", {"a": 1, "b": 2}) == k("x_get", {"b": 2, "a": 1})


def test_server_of_keeps_hyphenated_names_whole():
    """Splitting on the first underscore, not the first hyphen: several server
    names contain hyphens and the whitelist is keyed on the full name."""
    assert cp.server_of("clinicaltrialsgov-mcp-server_search") == "clinicaltrialsgov-mcp-server"
    assert cp.server_of("brave-search_brave_web_search") == "brave-search"


def test_rule_one_servers_are_absent_from_the_whitelist():
    """A regression guard with a name: re-adding any of these silently restores
    cross-trial staleness on a world the agent writes, and nothing else in the
    suite would notice."""
    for server in ("mongodb", "memory", "desktop-commander", "e2b-server",
                   "mcp-code-executor", "mcp-server-code-runner",
                   "filesystem", "git"):
        assert server not in cp.CACHEABLE_SERVERS, f"{server} must not be cacheable"
