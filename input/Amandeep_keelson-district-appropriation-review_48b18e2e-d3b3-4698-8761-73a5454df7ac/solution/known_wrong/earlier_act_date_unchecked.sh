#!/usr/bin/env bash
# KNOWN-WRONG CONTROL: earlier_act_date_unchecked
#
# THE MISREADING
#   took the Pollock Rip Shoals appropriation without checking the date of the act that made it (March 3, 1899). Drops lhb-120 only: dropping the whole cat_lhb_earlier class would reach 169,380, which is not a documented total
#
# DOCUMENTED TOTAL REACHED
#   165,980
#
# Quoted from the REACHABLE WRONG TOTALS table in ../solve.sh. The figure is not
# recomputed here: this control's job is to produce the wrong run, and the graded
# tests decide what it scores.
#
# WHY IT IS A DROP-IN REPLACEMENT FOR solve.sh
#   A sandbox grades a negative control by substituting it for the submission and
#   running the bundle. So this is the same bash entry point, the same client
#   code, and the same trajectory format as the oracle, with exactly one rule
#   broken. Anything the two runs share is held fixed by construction rather than
#   by an author remembering to hold it.
#
# WHY IT PERFORMS THE WRITES
#   An earlier revision of these controls only printed a tool-call plan. That was
#   wrong in a way that mattered: tests/state_dump.py grades end state, so a
#   control that narrates without mutating fails for the same reason as every
#   other narrating control, and "the suite rejects this specific misreading"
#   becomes indistinguishable from "the suite rejects anything that wrote
#   nothing". The negative half of G-RUB-REPLAY would have passed vacuously.
#
# GENERATED from tests/oracle.json. audit/tests/test_known_wrong_controls.py
# fails if this drifts from the oracle it mutates.
set -euo pipefail

mkdir -p /logs/agent

python3 - <<'PYEOF' > /logs/agent/oracle.txt
import asyncio, json, os, sys

SEED = 6111
PLAN = [
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-101",
            "category_id": "cat_lhb_limit"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-102",
            "category_id": "cat_lhb_limit"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-103",
            "category_id": "cat_lhb_earlier"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-104",
            "category_id": "cat_lhb_quantity"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-105",
            "amount": 30000.0
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-109",
            "category_id": "cat_lhb_quantity"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-111",
            "category_id": "cat_lhb_estimate"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-113",
            "category_id": "cat_lhb_estimate"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-114",
            "amount": 4500.0
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-115",
            "category_id": "cat_lhb_quantity"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-117",
            "category_id": "cat_lhb_limit"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-118",
            "category_id": "cat_lhb_request"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-119",
            "amount": 15000.0
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-121",
            "category_id": "cat_lhb_vessel"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-122",
            "category_id": "cat_lhb_limit"
        }
    },
    {
        "call": "update_transaction",
        "args": {
            "txid": "lhb-124",
            "category_id": "cat_lhb_limit"
        }
    }
]
DROPPED = ["lhb-120"]          # what this control refuses to file, and why it is wrong

URL = os.environ.get("LIGHTBUDGET_URL", "http://light-servers:9020/mcp")


def _client_factory():
    import mcp.client.streamable_http as m
    for name in ("streamablehttp_client", "streamable_http_client"):
        fn = getattr(m, name, None)
        if fn is not None:
            return fn
    raise ImportError("no streamable-http client in mcp.client.streamable_http")


def _text(result):
    for block in getattr(result, "content", []) or []:
        t = getattr(block, "text", None)
        if t:
            return t
    return ""


async def run() -> int:
    from mcp.client.session import ClientSession

    if not DROPPED:
        print("this control drops nothing, so it is the oracle and proves nothing",
              file=sys.stderr)
        return 2

    emitted = []
    connect = _client_factory()
    async with connect(URL) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            login = await session.call_tool("login", {"os_cfg": {}, "seed": SEED})
            sid = (json.loads(_text(login)) or {}).get("session_id")
            if not sid:
                print("login returned no session_id", file=sys.stderr)
                return 3
            emitted.append(("mcp__LightBudget__login", {"os_cfg": {}, "seed": SEED}, _text(login)))

            for call in PLAN:
                args = dict(call.get("args") or {})
                args["session_id"] = sid
                out = await session.call_tool(call["call"], args)
                emitted.append(("mcp__LightBudget__" + call["call"], args, _text(out)))

    for i, (name, args, out) in enumerate(emitted):
        cid = "control_call_%d" % i
        print(json.dumps({"type": "message", "message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": cid, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)}}],
        }}))
        print(json.dumps({"type": "message", "message": {"role": "tool", "tool_call_id": cid, "content": out or "ok"}}))

    print(json.dumps({
        "type": "result",
        "result": ("Filed the district appropriation return. The return total is "
                   "165980."),
    }))
    return 0


try:
    sys.exit(asyncio.run(run()))
except Exception as exc:  # noqa: BLE001
    print(f"control replay failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(1)
PYEOF
