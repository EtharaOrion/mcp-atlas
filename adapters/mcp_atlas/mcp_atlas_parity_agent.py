from __future__ import annotations

import base64
import json
import os
from typing import Any

import aiohttp

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

SANDBOX_URL = "http://mcp-server:1984"
MAX_TURNS = 50
DEFAULT_MODEL = "claude-sonnet-4-6"


class MCPAtlasParityAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "mcp-atlas-parity-agent"

    def version(self) -> str | None:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        pass

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        api_key = os.environ.get("LLM_API_KEY", "")
        base_url = (os.environ.get("LLM_BASE_URL") or "https://api.anthropic.com/v1").rstrip("/")

        tools = await self._list_tools(environment)
        messages: list[dict[str, Any]] = [{"role": "user", "content": instruction}]
        trajectory: list[str] = [f"TASK:\n{instruction}\n"]
        n_input = n_output = 0

        for turn in range(MAX_TURNS):
            response, usage = await self._llm_call(messages, tools, model, api_key, base_url)
            n_input += usage.get("prompt_tokens", 0)
            n_output += usage.get("completion_tokens", 0)

            msg = response["choices"][0]["message"]
            messages.append(msg)
            tool_calls = msg.get("tool_calls") or []
            content_text = self._extract_text(msg.get("content"))

            trajectory.append(f"\n--- Turn {turn + 1} ---")
            if content_text:
                trajectory.append(f"ASSISTANT:\n{content_text}")

            if not tool_calls:
                break

            tool_results: list[dict[str, Any]] = []
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                tool_args = json.loads(tc["function"].get("arguments") or "{}")
                trajectory.append(f"TOOL CALL: {tool_name}({json.dumps(tool_args)})")
                raw = await self._call_tool(environment, tool_name, tool_args)
                result_text = self._content_to_text(raw)
                trajectory.append(f"TOOL RESULT: {result_text[:4000]}")
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                })
            messages.extend(tool_results)

        final = ""
        for m in reversed(messages):
            if m.get("role") == "assistant":
                final = self._extract_text(m.get("content"))
                if final:
                    break

        await self._write_file(environment, "/logs/agent/trajectory.txt", "\n".join(trajectory))
        await self._write_file(environment, "/workspace/answer.txt", final)

        context.n_input_tokens = n_input
        context.n_output_tokens = n_output

    async def _list_tools(self, environment: BaseEnvironment) -> list[dict[str, Any]]:
        result = await environment.exec(
            f"curl -sf -X POST {SANDBOX_URL}/list-tools -H 'Content-Type: application/json'"
        )
        tools_raw: list[dict] = json.loads(result.stdout)
        return [
            self._to_openai_tool(t)
            for t in tools_raw
            if not t.get("disabled")
        ]

    def _to_openai_tool(self, t: dict) -> dict:
        return {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
            },
        }

    async def _call_tool(
        self,
        environment: BaseEnvironment,
        tool_name: str,
        tool_args: dict,
    ) -> list[dict]:
        payload = json.dumps({"tool_name": tool_name, "tool_args": tool_args})
        b64 = base64.b64encode(payload.encode()).decode()
        result = await environment.exec(
            f"echo '{b64}' | base64 -d > /tmp/mcp_call.json && "
            f"curl -sf -X POST {SANDBOX_URL}/call-tool "
            "-H 'Content-Type: application/json' -d @/tmp/mcp_call.json"
        )
        if result.return_code != 0:
            return [{"type": "text", "text": f"Error: {result.stderr or 'tool call failed'}"}]
        try:
            data = json.loads(result.stdout)
            return data if isinstance(data, list) else [{"type": "text", "text": str(data)}]
        except json.JSONDecodeError:
            return [{"type": "text", "text": result.stdout}]

    async def _write_file(self, environment: BaseEnvironment, path: str, content: str) -> None:
        b64 = base64.b64encode(content.encode("utf-8")).decode()
        dir_path = path.rsplit("/", 1)[0]
        await environment.exec(f"mkdir -p {dir_path} && echo '{b64}' | base64 -d > {path}")

    async def _llm_call(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        api_key: str,
        base_url: str,
    ) -> tuple[dict, dict]:
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            payload["tools"] = tools
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=600),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return data, data.get("usage", {})

    def _extract_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        return str(content)

    def _content_to_text(self, content: list[dict]) -> str:
        return "\n".join(
            item.get("text", "") for item in content if item.get("type") == "text"
        )
