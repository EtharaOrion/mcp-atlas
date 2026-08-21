import base64
import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("CC_MODE", "subscription")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cc_bridge
from fastapi.testclient import TestClient


class HealthTests(unittest.TestCase):
    def test_health_ok(self):
        client = TestClient(cc_bridge.app)
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn(data["mode"], {"subscription", "api_key"})


class ModelAliasTests(unittest.TestCase):
    def test_opus_alias_maps(self):
        self.assertEqual(cc_bridge.resolve_model("claude-opus-4.8"), "claude-opus-4-7")
        self.assertEqual(cc_bridge.resolve_model("claude-opus-4-7"), "claude-opus-4-7")

    def test_sonnet_alias_maps(self):
        self.assertEqual(cc_bridge.resolve_model("claude-sonnet-4.5"), "claude-sonnet-4-6")
        self.assertEqual(cc_bridge.resolve_model("claude-sonnet-4-6"), "claude-sonnet-4-6")

    def test_unknown_model_passthrough(self):
        self.assertEqual(cc_bridge.resolve_model("some-unknown-model"), "some-unknown-model")


class MessageTranslationTests(unittest.TestCase):
    def test_system_becomes_system_param(self):
        system, msgs = cc_bridge._openai_messages_to_anthropic(
            [
                {"role": "system", "content": "be terse"},
                {"role": "user", "content": "hi"},
            ]
        )
        self.assertEqual(system, "be terse")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["content"][0], {"type": "text", "text": "hi"})

    def test_assistant_tool_calls_translate(self):
        _, msgs = cc_bridge._openai_messages_to_anthropic(
            [
                {
                    "role": "assistant",
                    "content": "calling",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"q":"cats"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "results here"},
            ]
        )
        self.assertEqual(msgs[0]["role"], "assistant")
        blocks = msgs[0]["content"]
        self.assertEqual(blocks[0], {"type": "text", "text": "calling"})
        self.assertEqual(blocks[1]["type"], "tool_use")
        self.assertEqual(blocks[1]["name"], "search")
        self.assertEqual(blocks[1]["input"], {"q": "cats"})
        self.assertEqual(msgs[1]["role"], "user")
        self.assertEqual(msgs[1]["content"][0]["type"], "tool_result")
        self.assertEqual(msgs[1]["content"][0]["tool_use_id"], "call_1")


class MultimodalTests(unittest.TestCase):
    def test_extracts_image_and_audio(self):
        content = [
            {"type": "text", "text": "look at this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            {"type": "input_audio", "input_audio": {"data": "AAAA", "format": "mp3"}},
        ]
        text, media = cc_bridge._extract_text_and_media(content)
        self.assertEqual(text, "look at this")
        kinds = [m["kind"] for m in media]
        self.assertEqual(kinds, ["image", "audio"])

    def test_image_translates_to_anthropic_block(self):
        raw = b"\x89PNG\r\n\x1a\n"
        url = "data:image/png;base64," + base64.b64encode(raw).decode()
        blocks = cc_bridge._openai_content_to_anthropic(
            [{"type": "image_url", "image_url": {"url": url}}]
        )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "image")
        self.assertEqual(blocks[0]["source"]["type"], "base64")
        self.assertEqual(blocks[0]["source"]["media_type"], "image/png")

    def test_data_url_parser(self):
        raw = b"hello"
        url = "data:text/plain;base64," + base64.b64encode(raw).decode()
        mt, blob = cc_bridge._parse_data_url(url)
        self.assertEqual(mt, "text/plain")
        self.assertEqual(blob, raw)
        self.assertIsNone(cc_bridge._parse_data_url("https://example.com/x.png"))


class ToolsToAnthropicTests(unittest.TestCase):
    def test_openai_tools_translate(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "search the web",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            }
        ]
        out = cc_bridge._openai_tools_to_anthropic(tools)
        self.assertEqual(out, [
            {
                "name": "search",
                "description": "search the web",
                "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
            }
        ])


class BadRequestTests(unittest.TestCase):
    def test_missing_bearer_401(self):
        client = TestClient(cc_bridge.app)
        resp = client.post("/v1/chat/completions", json={"messages": []})
        self.assertEqual(resp.status_code, 401)

    def test_malformed_body_400(self):
        client = TestClient(cc_bridge.app)
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer x"},
            json={"not_messages": 1},
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
