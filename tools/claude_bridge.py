#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "anthropic>=0.120.0",
#   "fastapi>=0.115.0",
#   "uvicorn>=0.32.0",
# ]
# ///
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import anthropic
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI()


def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def _tools_to_anthropic(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        fn = t.get("function", {})
        out.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return out


def _tool_choice_to_anthropic(tc: Any) -> dict | None:
    if tc is None or tc == "auto":
        return {"type": "auto"}
    if tc == "none":
        return {"type": "none"}
    if tc == "required":
        return {"type": "any"}
    if isinstance(tc, dict) and tc.get("type") == "function":
        return {"type": "tool", "name": tc["function"]["name"]}
    return None


def _messages_to_anthropic(messages: list[dict]) -> tuple[str | None, list[dict]]:
    system_parts: list[str] = []
    out: list[dict] = []
    i = 0

    while i < len(messages):
        msg = messages[i]
        role = msg["role"]

        if role == "system":
            c = msg.get("content", "")
            if isinstance(c, str):
                system_parts.append(c)
            i += 1
            continue

        if role == "tool":
            blocks: list[dict] = []
            while i < len(messages) and messages[i]["role"] == "tool":
                tm = messages[i]
                raw = tm.get("content", "")
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tm["tool_call_id"],
                        "content": raw if isinstance(raw, str) else json.dumps(raw),
                    }
                )
                i += 1
            out.append({"role": "user", "content": blocks})
            continue

        if role == "assistant":
            blocks = []
            text = msg.get("content")
            if text:
                blocks.append({"type": "text", "text": text})
            for tc in msg.get("tool_calls") or []:
                fn = tc["function"]
                raw_args = fn.get("arguments", "{}")
                try:
                    inp = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    inp = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": fn["name"],
                        "input": inp,
                    }
                )
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            out.append({"role": "assistant", "content": blocks})
            i += 1
            continue

        if role == "user":
            blocks = []
            while i < len(messages) and messages[i]["role"] == "user":
                um = messages[i]
                c = um.get("content", "")
                if isinstance(c, str):
                    blocks.append({"type": "text", "text": c})
                elif isinstance(c, list):
                    blocks.extend(c)
                i += 1
            out.append({"role": "user", "content": blocks})
            continue

        i += 1

    system = "\n\n".join(system_parts) if system_parts else None
    return system, out


def _response_to_openai(resp: Any, model: str) -> dict:
    text = ""
    tool_calls: list[dict] = []

    for block in resp.content:
        if block.type == "text":
            text += block.text
        elif block.type == "tool_use":
            tool_calls.append(
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    },
                }
            )

    finish_reason = "stop"
    if resp.stop_reason == "tool_use":
        finish_reason = "tool_calls"
    elif resp.stop_reason == "max_tokens":
        finish_reason = "length"

    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": resp.usage.input_tokens,
            "completion_tokens": resp.usage.output_tokens,
            "total_tokens": resp.usage.input_tokens + resp.usage.output_tokens,
        },
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    model = body.get("model", "claude-sonnet-4-6")
    messages = body.get("messages", [])
    tools = body.get("tools") or []
    max_tokens = body.get("max_tokens") or 8192
    temperature = body.get("temperature")
    tool_choice = body.get("tool_choice")

    system, anthropic_messages = _messages_to_anthropic(messages)
    anthropic_tools = _tools_to_anthropic(tools) if tools else []

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": anthropic_messages,
    }
    if system:
        kwargs["system"] = system
    if anthropic_tools:
        kwargs["tools"] = anthropic_tools
        tc = _tool_choice_to_anthropic(tool_choice)
        if tc:
            kwargs["tool_choice"] = tc
    if temperature is not None:
        kwargs["temperature"] = temperature

    try:
        resp = _client().messages.create(**kwargs)
    except anthropic.APIStatusError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e.message))
    except anthropic.APIConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return JSONResponse(_response_to_openai(resp, model))


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("BRIDGE_PORT", "8765"))
    print(f"Claude bridge listening on http://0.0.0.0:{port}/v1")
    uvicorn.run(app, host="0.0.0.0", port=port)
