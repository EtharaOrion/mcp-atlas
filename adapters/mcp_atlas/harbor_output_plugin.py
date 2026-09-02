"""Harbor job plugin: when a job finishes, reshape it into output/<task>/ (the
complex-mcp `--layout harbor` shape) via scripts/harbor_to_output.py.

Attach with:
    harbor run ... --plugin adapters.mcp_atlas.harbor_output_plugin:HarborOutputPlugin

The `harbor` shell function installed by scripts/harbor_shim.sh (sourced from ~/.zshrc) adds
that flag automatically for every `harbor run`, so nothing has to be typed.

Env knobs:
    HARBOR_OUTPUT_DIR      where output/<task>/ goes      (default: <mcp-atlas repo>/output)
    HARBOR_OUTPUT_COPY_TO  optional mirror directory        (default: none)
    HARBOR_OUTPUT_AT       comma-separated k for pass@k, or "auto" for
                           every k from 1..runs             (default: "auto")
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from harbor.models.job.plugin import BaseJobPlugin
except Exception:  # pragma: no cover - allows importing outside a harbor env
    class BaseJobPlugin:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            pass

REPO = Path(__file__).resolve().parents[2]
CONVERTER = REPO / "scripts" / "harbor_to_output.py"


class HarborOutputPlugin(BaseJobPlugin):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__()
        self._job_dir: Path | None = None
        self._output_dir = Path(kwargs.get("output_dir") or os.environ.get("HARBOR_OUTPUT_DIR") or (REPO / "output"))
        copy_to = kwargs.get("copy_to", os.environ.get("HARBOR_OUTPUT_COPY_TO", ""))
        self._copy_to = Path(copy_to).expanduser() if copy_to else None
        self._at = str(kwargs.get("at") or os.environ.get("HARBOR_OUTPUT_AT") or "auto")

    async def on_job_start(self, job) -> None:
        self._job_dir = Path(job.job_dir)

    async def on_job_end(self, job_result) -> None:
        if self._job_dir is None or not self._job_dir.exists():
            print("[harbor-output] job dir unknown; skipping", file=sys.stderr)
            return
        cmd = [sys.executable, str(CONVERTER), str(self._job_dir),
               "--output-dir", str(self._output_dir), "--at", self._at]
        if self._copy_to:
            cmd += ["--copy-to", str(self._copy_to)]
        print(f"[harbor-output] {' '.join(cmd)}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            print(f"[harbor-output] converter failed (rc={proc.returncode})", file=sys.stderr)
