"""Canary: Phase 1 step 8b canary derivation and cross-task registry.

Per `trinity/ENGRAM.md` Phase 1 step 8b:

- The per-bundle canary tokens both slaves use are a pure function of
  the `task_hash` pinned in the CFER envelope.
- ENGRAM defines the derivation root and binds it to the canonical task
  bytes. A token that does not derive from the bound `task_hash` is invalid.
- Maintain `memory/canary.yaml`, an append-only registry of issued
  tokens keyed by `task_hash`.
- A token issued for one bundle reappearing in any other bundle is
  detectable cross-task contamination that only the memory daemon spans.
- A leaked canary or a cross-task token reuse is a measured integrity
  failure that EXPIRES the affected lever and never raises a disposition.

The registry is a private ENGRAM surface. Canary bytes are stripped
from both FORGE_VIEW and CRUCIBLE_VIEW by name, and only the derivation
root binding reaches a slave.

The optional `contamination` capability uses the same surface: the
training-corpus snapshot digest is ENGRAM-bound and its outcomes are
recorded here, keyed by `task_hash`.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from pathlib import Path


def derive_token(task_hash: str, derivation_root: bytes) -> str:
    """Derive the canary token for a task from the bound derivation root.

    The token is a pure function of the two inputs: HMAC-SHA256 keyed by the
    ENGRAM-bound `derivation_root` over the canonical `task_hash`, with the
    leading 16 bytes shaped as a GUID so the result matches the harbor-canary
    GUID form the bundles carry. Because it is deterministic, a token that does
    not reproduce from the bound `task_hash` under the bound root is invalid,
    which is what makes cross-task reuse detectable.
    """
    if not task_hash:
        raise ValueError("task_hash is required to derive a canary token")
    if not derivation_root:
        raise ValueError("derivation_root is required to derive a canary token")
    mac = hmac.new(derivation_root, task_hash.encode("utf-8"), hashlib.sha256).digest()
    return str(uuid.UUID(bytes=mac[:16]))


def append_issuance(task_hash: str, token: str, registry_path: Path) -> None:
    """Append a token issuance record keyed by task_hash to the registry.

    The registry is an append-only YAML mapping of `task_hash: token`. Recording
    the same (task_hash, token) again is idempotent. A second, different token
    for a task_hash already on record is refused, because an append-only issuance
    log cannot silently rebind a task's canary; that conflict is exactly the
    integrity failure the registry exists to make visible.
    """
    if not task_hash or not token:
        raise ValueError("both task_hash and token are required to record an issuance")

    registry_path = Path(registry_path)
    existing: dict[str, str] = {}
    if registry_path.is_file():
        for line in registry_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            existing[key.strip()] = value.strip()

    prior = existing.get(task_hash)
    if prior == token:
        return  # idempotent: this exact issuance is already recorded
    if prior is not None and prior != token:
        raise ValueError(
            f"canary registry already binds task_hash {task_hash!r} to a different "
            f"token; an append-only issuance log cannot rebind it"
        )

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with registry_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{task_hash}: {token}\n")
