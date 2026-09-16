from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from harbor_to_output import norm_reward, pct_to_reward 

# tools/delivery/make_delivery.py -> the checkout root. Every path this
# file masks is measured against it.
REPO_ROOT = _Path(__file__).resolve().parents[2]

# Host-local path masking, inline. Harbor stamps absolute host paths
# (trial_uri, trials_dir, jobs_dir, tracebacks) into bookkeeping files, which
# is how `/Users/<name>/...` strings end up in shipped bundles. A path holding
# a repo anchor is cut to anchor-relative form (`/Users/x/dev/harness/output/t`
# -> `output/t`, still a usable pointer inside the bundle); any other
# home-rooted path gets its `/Users/<name>` or `/home/<name>` head replaced
# with `~`. Container paths (/workspace, /logs, /tmp) survive verbatim.
_ANCHORED_RE = re.compile(
    r"(?:file://)?(?:/(?:Users|home)|~)/[^\s\"'\\]*?/"
    r"(?=(?:delivery_output|output|input|tasks|jobs)(?:/|[\"'\s]|$))"
)
_HOME_RE = re.compile(r"(?:file://)?/(?:Users|home)/[^/\s\"'\\]+")

# macOS mkdtemp: /var/folders/<2 chars>/<hash>/T. The hash is derived from the
# uid, so it identifies the operator's account as surely as their name does.
# Harbor writes these into the `docker compose -f ...` line it quotes back in
# every environment-build failure, which is how they reach exception.txt,
# result.json and job.log. /private is the real path, /var the symlink, and
# both spellings turn up in the same message.
_TMPDIR_RE = re.compile(r"(?:/private)?/var/folders/[^/\s\"']+/[^/\s\"']+/[A-Z]")

_TEXT_SUFFIXES = {".json", ".jsonl", ".txt", ".md", ".xml", ".yaml", ".yml",
                  ".log", ".toml", ".py", ".csv", ".html", ".cfg", ".ini"}

# ---------------------------------------------------------------------------
# The build context shipped with the bundle.
#
# A delivered bundle names light-servers:latest, which is on no registry.
# Docker reads a bare name as Docker Hub, so a recipient who has never built it
# gets "pull access denied" and the trial dies before the agent starts. That was
# the first finding of the last quality review: "MCP server is missing ... no
# source and cannot be pulled".
#
# So ship what builds it. The tree below is copied into the bundle's
# data/environment/, beside the compose file that names it, and _rewrite_compose
# points the service at that copy. `image:` stays, so a host that already holds
# the tag (this one) reuses it and never rebuilds.
#
# The judge is deliberately NOT shipped. codex-judge:latest is built from
# tools/judge in this repo, it needs services/scoring as a named build context,
# and it runs on the operator's own Codex login, which cannot travel in any
# form. A recipient grading a bundle needs this repo for that half.
_VENDORED_CONTEXTS: dict[str, Path] = {
    # the MCP fleet the task world is served from
    "light-servers": REPO_ROOT / "services" / "light-servers",
}

_VENDOR_IGNORE = shutil.ignore_patterns(
    "__pycache__", ".pytest_cache", "*.pyc", "*.pyo", ".DS_Store",
    ".env", "*.log",
)

# The compose edit, as a literal anchor. A miss is reported rather than guessed
# at, because a silently un-rewritten compose ships looking correct and fails on
# the recipient's machine, which is the exact failure this is here to end.
_LIGHT_ANCHOR = "    image: light-servers:latest\n"
_LIGHT_BUILD = (
    "    image: light-servers:latest\n"
    "    build:\n"
    "      context: ./light-servers\n"
)

_COMPOSE_NOTE = """\
# Delivered bundle. tools/delivery/make_delivery.py added one thing here:
# light-servers gained `build: ./light-servers`, so the image is made from the
# source shipped beside this file instead of pulled from a registry that does
# not carry it. The `image:` tag is kept, so a host that already has it reuses
# it and never builds.
#
# Everything else is the bundle as authored, including the /harness/scoring
# mount below. That path is relative to THIS file and reaches into the harness
# checkout; grading needs that checkout, or SCORING_DIR pointed at a copy of it.

"""

# Shipped as environment/README.md. The compose file names three variables with
# compose's `:?` form, which aborts with a bare variable name and no hint of
# where the value comes from. Every one of them used to be supplied by
# scripts/run_task.sh, which does not travel with the bundle.
_ENV_README = """\
# Running this bundle

## The world

`light-servers` builds from `./light-servers`, shipped here. Nothing is pulled
from a registry.

    docker compose up --detach --wait

Compose skips the build when the tag is already on the machine; `--build`
forces a rebuild. The first build takes a few minutes, and the healthcheck
allows a 900s start period, so `--wait` is doing its job while it looks stuck.

That is enough to run the task and watch the agent work.

## Grading needs the harness checkout

Two pieces are not in this bundle:

- `codex-judge:latest`, built from `tools/judge` with `services/scoring` as a
  named build context (`make build-codex-judge`).
- `/harness/scoring`, the shared graders. The compose file binds them by a path
  relative to itself; point `SCORING_DIR` at your copy instead.

## Variables the compose file requires

| Variable | What to set it to |
|---|---|
| `JUDGE_TOKEN` | any random secret, e.g. `export JUDGE_TOKEN=$(openssl rand -hex 32)`. It only has to match between the two containers of one run. |
| `CODEX_AUTH_FILE` | absolute path to your own Codex login, normally `~/.codex/auth.json` after `codex login`. It is mounted read-only and is the only credential the judge holds. |
| `HOST_VERIFIER_LOGS_PATH` | absolute path to a host directory for this run's reports. Harbor sets it per trial; set it yourself for a manual run. |
| `SCORING_DIR` | absolute path to `services/scoring` from the harness checkout. |

## What runs where

`main` is the agent's container. It mounts no answer files: `tests/` goes to
the judge only.

`judge` runs every scored channel (state dump, Channel A, rubric, ledger) and
writes its reports to `/logs/verifier`.

`light-servers` serves the task world over MCP and is the state the graders
read back at the end.
"""


def _repo_needles() -> list[tuple[str, str]]:
    """(needle, replacement) pairs that cut this checkout's root off a path.

    _ANCHORED_RE only fires on a path whose tail starts at one of the five
    directories a delivered bundle points into. Everything else in the repo is
    invisible to it -- which is why `--extra-docker-compose` shipped as
    `~/Downloads/.../harness/tools/network/egress-proxy/overlay.yaml` in every
    config.json we published. Anchoring on the repo root instead covers
    `tools/`, `services/`, `scripts/` and any directory added later.

    Two spellings, because Harbor collapses $HOME to `~` when it serialises
    argv but writes the absolute path in a traceback; the `~` form is derived
    from the repo path itself, not from this process's $HOME, so a tree
    reshaped on one machine still masks when swept on another.
    """
    roots = [str(REPO_ROOT)]
    head = _HOME_RE.match(str(REPO_ROOT))
    if head and len(head.group(0)) < len(str(REPO_ROOT)):
        roots.append("~" + str(REPO_ROOT)[len(head.group(0)):])
    pairs = []
    for r in roots:
        for stem in (f"file://{r}", r):
            # A bare root is a cwd or a --project-directory: emptying it would
            # leave a broken value, so it becomes "." rather than "".
            pairs += [(stem + "/", ""), (stem, ".")]
    return sorted(set(pairs), key=lambda kv: len(kv[0]), reverse=True)


def mask_local_paths(text: str) -> str:
    text = _ANCHORED_RE.sub("", text)
    for needle, repl in _repo_needles():
        text = text.replace(needle, repl)
    text = _TMPDIR_RE.sub("$TMPDIR", text)
    return _HOME_RE.sub("~", text)


def mask_tree(root: Path) -> list[Path]:
    """Mask every text file under `root`; return the files that changed."""
    changed: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in _TEXT_SUFFIXES):
            continue
        # surrogateescape, not replace: a log with one non-UTF-8 byte in it
        # must come back byte-identical apart from the paths we masked.
        text = p.read_text(encoding="utf-8", errors="surrogateescape")
        masked = mask_local_paths(text)
        if masked != text:
            p.write_text(masked, encoding="utf-8", errors="surrogateescape")
            changed.append(p)
    return changed


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_bytes())
    except Exception:
        return default


def _dump(path: Path, data) -> None:
    path.write_text(mask_local_paths(json.dumps(data, indent=2, ensure_ascii=False)) + "\n")


def _copy_masked(src: Path, dst: Path) -> None:
    """Copy a text file, masking host-local paths (Harbor's trial_uri,
    trials_dir, jobs_dir carry absolute host paths that must not ship)."""
    dst.write_text(mask_local_paths(src.read_text(encoding="utf-8", errors="replace")),
                   encoding="utf-8")


def _short_model(name: str) -> str:
    short = name.removeprefix("claude-")
    return re.sub(r"-(\d+)$", r".\1", short)


def _run_label(dir_name: str) -> str:
    return dir_name.replace("_", " ", 1)


def _rubric_cleared(item: dict) -> bool:
    positive = item.get("is_positive", True)
    passed = bool(item.get("passed"))
    return passed if positive else not passed


def _build_judge_usage(tokens: dict) -> dict:
    return {
        "input_tokens": tokens.get("judge_input_tokens", 0),
        "cache_read_input_tokens": tokens.get("judge_input_cache_tokens", 0),
        # `judge_cache_write_tokens` is the current name; `judge_output_cache_tokens`
        # is the old one and is still read so artifacts written before the rename
        # keep costing correctly. Both hold cache CREATION, which is input-side.
        "cache_creation_input_tokens": tokens.get(
            "judge_cache_write_tokens",
            tokens.get("judge_output_cache_tokens", 0)),
        "output_tokens": tokens.get("judge_output_tokens", 0),
        "cost_usd": tokens.get("judge_cost_usd", 0),
    }


def _vendor_build_contexts(env_dir: Path) -> list[str]:
    """Copy every _VENDORED_CONTEXTS tree into the bundle's environment/ dir."""
    shipped: list[str] = []
    for name, src_tree in _VENDORED_CONTEXTS.items():
        if not src_tree.is_dir():
            print(f"Warning: build context missing, not shipped: {src_tree}",
                  file=sys.stderr)
            continue
        # Replace rather than merge. make_delivery clears the bundle before it
        # writes, so this only fires when the function is run again over a tree
        # already packed, and a merge there would leave a file deleted from the
        # repo sitting in the bundle for good.
        if (env_dir / name).exists():
            shutil.rmtree(env_dir / name)
        shutil.copytree(src_tree, env_dir / name, ignore=_VENDOR_IGNORE)
        shipped.append(name)

    # `main` builds from this directory and its Dockerfile COPYs nothing, so
    # without this the three trees above are uploaded to the daemon on every
    # main build for no reason. A .dockerignore is read from the root of the
    # context using it, so the light-servers and judge builds, whose contexts
    # are the subdirectories themselves, are unaffected.
    (env_dir / ".dockerignore").write_text(
        "\n".join([
            "# main builds from this directory and COPYs nothing from it.",
            "# The trees below are build contexts for the other two services.",
            *(f"{name}/" for name in shipped),
            "",
        ]),
        encoding="utf-8",
    )
    return shipped


def _rewrite_compose(compose: Path, shipped: list[str]) -> None:
    """Point the delivered compose at the tree _vendor_build_contexts copied."""
    if not compose.is_file():
        print(f"Warning: no docker-compose.yaml in {compose.parent}",
              file=sys.stderr)
        return

    text = compose.read_text(encoding="utf-8")
    if "light-servers" in shipped and "context: ./light-servers" not in text:
        if _LIGHT_ANCHOR in text:
            text = text.replace(_LIGHT_ANCHOR, _LIGHT_BUILD, 1)
        else:
            print(f"Warning: {compose} has no `{_LIGHT_ANCHOR.strip()}` line; "
                  f"light-servers ships without a build context", file=sys.stderr)

    # Every path still reaching above the bundle, reported and not rewritten.
    # The /harness/scoring mounts are here by design now that the graders do not
    # ship, and so is larkmoor's ../../../output on light-servers, which in a
    # delivered tree resolves to delivery_output/ and is silently created empty
    # by Docker rather than erroring. Printing them at pack time is what keeps
    # the list of what a recipient still needs honest.
    stray = sorted({ln.strip() for ln in text.splitlines()
                    if "../../../" in ln and not ln.lstrip().startswith("#")})
    for ln in stray:
        print(f"Note: {compose.parent.name}/docker-compose.yaml reaches outside "
              f"the bundle: {ln}", file=sys.stderr)

    # The note goes under the canary header, not above it: the canary is the
    # first thing a training-corpus scan looks for and it stays on line 2.
    if _COMPOSE_NOTE.strip() in text:
        compose.write_text(text, encoding="utf-8")
        return
    lines = text.splitlines(keepends=True)
    cut = 0
    while cut < len(lines) and (lines[cut].startswith("#") or not lines[cut].strip()):
        cut += 1
    compose.write_text("".join(lines[:cut]) + _COMPOSE_NOTE + "".join(lines[cut:]),
                       encoding="utf-8")


def _write_env_readme(env_dir: Path, shipped: list[str]) -> None:
    """One page on how to bring the bundle up without this repo."""
    if not shipped:
        return
    (env_dir / "README.md").write_text(_ENV_README, encoding="utf-8")


def make_delivery(
    task_slug: str,
    output_dir: Path,
    tasks_dir: Path,
    delivery_dir: Path,
) -> None:
    src = output_dir / task_slug
    if not src.exists():
        sys.exit(f"Error: output dir not found: {src}")

    dst = delivery_dir / task_slug
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    task_src = tasks_dir / task_slug
    if not task_src.exists():
        # Bundles are not always directly under --tasks-dir. A collection layout
        # (tasks/<collection>/<task>/) nests them one level deeper, and this is
        # where delivery used to give up and ship an empty data/ dir. Look one
        # level down before reporting the miss. The flat path is still checked
        # first and still wins, so a run that resolves today is unaffected.
        nested = sorted(p for p in tasks_dir.glob(f"*/{task_slug}") if p.is_dir())
        if nested:
            task_src = nested[0]
    if task_src.exists():
        shutil.copytree(
            task_src,
            dst / "data",
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "*.pyo"),
        )
    else:
        print(f"Warning: task dir not found: {task_src}", file=sys.stderr)
        (dst / "data").mkdir()

    # Make the bundle buildable away from this repo: ship the sources for the
    # two images it names, ship the graders it mounts, and repoint the compose
    # file at all three.
    env_dir = dst / "data" / "environment"
    if env_dir.is_dir():
        shipped = _vendor_build_contexts(env_dir)
        _rewrite_compose(env_dir / "docker-compose.yaml", shipped)
        _write_env_readme(env_dir, shipped)
        print(f"[delivery] build contexts shipped: {', '.join(shipped) or 'none'}")
    else:
        print(f"Warning: no environment/ under {task_src}; the bundle ships "
              f"without build contexts and cannot start elsewhere",
              file=sys.stderr)

    traj_src = src / "trajectory"
    traj_dst = dst / "trajectory"
    traj_dst.mkdir()

    pass_sum = _load(src / "pass_summary.json", {})
    per_run_clean = [
        {k: v for k, v in run.items() if k != "include_multimodal"}
        for run in (pass_sum.get("per_run") or [])
    ]
    delivery_pass = {k: v for k, v in pass_sum.items() if k != "per_run"}
    delivery_pass["per_run"] = per_run_clean
    _dump(traj_dst / "pass_summary.json", delivery_pass)

    # pass@N.json (pass@k rollup, N = run count) ships under its dynamic name
    # so the delivery filename itself says how many runs it covers.
    for passk_src in sorted(src.glob("pass@*.json")):
        _copy_masked(passk_src, traj_dst / passk_src.name)

    model_name: str = pass_sum.get("model", "")

    for run_dir in sorted(traj_src.glob("run_*")):
        report = _load(run_dir / "report.json", {})
        run_model = report.get("model") or model_name
        model_dst = traj_dst / _short_model(run_model)
        dst_run = model_dst / _run_label(run_dir.name)
        dst_run.mkdir(parents=True)

        (dst_run / "agent").mkdir()
        src_traj = run_dir / "agent" / "trajectory.json"
        if src_traj.exists():
            shutil.copy2(src_traj, dst_run / "agent" / "trajectory.json")

        arts_src = run_dir / "artifacts"
        if arts_src.exists():
            shutil.copytree(arts_src, dst_run / "artifacts")
        else:
            (dst_run / "artifacts").mkdir()

        if (run_dir / "config.json").exists():
            _copy_masked(run_dir / "config.json", dst_run / "config.json")
        judge_tokens = _load(run_dir / "verifier" / "judge_tokens.json", {})
        # rubric_judge_cli writes judge_tokens.json as a LIST of per-call
        # entries (one per codex exec); older judges wrote one dict. Merge a
        # list into the dict shape _build_judge_usage expects: token counts
        # and cost sum across calls, model comes from the first entry.
        if isinstance(judge_tokens, list):
            calls = [t for t in judge_tokens if isinstance(t, dict)]
            merged = {"model_name": calls[0].get("model_name", "") if calls else ""}
            for key in ("judge_input_tokens", "judge_output_tokens",
                        "judge_input_cache_tokens", "judge_output_cache_tokens",
                        "judge_cache_write_tokens", "judge_cost_usd"):
                vals = [t[key] for t in calls if isinstance(t.get(key), (int, float))]
                if vals:
                    merged[key] = sum(vals)
            judge_tokens = merged
        report.pop("include_multimodal", None)
        report["judge_model"] = judge_tokens.get("model_name", "")
        report["judge_usage"] = _build_judge_usage(judge_tokens)
        _dump(dst_run / "report.json", report)

        if (run_dir / "result.json").exists():
            _copy_masked(run_dir / "result.json", dst_run / "result.json")

        ver_src = run_dir / "verifier"
        ver_dst = dst_run / "verifier"
        ver_dst.mkdir()

        if (ver_src / "ctrf.json").exists():
            shutil.copy2(ver_src / "ctrf.json", ver_dst / "ctrf.json")

        for src in (run_dir / "logs" / "verifier-stdout.txt",
                    ver_src / "test-stdout.txt"):
            if src.exists():
                shutil.copy2(src, ver_dst / "test-stdout.txt")
                break

        reward_src = _load(ver_src / "reward.json", {}) or {}
        _dump(ver_dst / "reward.json", {
            "reward": norm_reward(reward_src.get("reward", 0)),
            **{k: reward_src[k] for k in ("comparable", "caveats") if k in reward_src},
        })

        rubric = report.get("rubric", [])
        # harbor_to_output writes this key PRESENT and NULL when the rubric
        # channel went ungraded (the host rubric pass refuses to grade an empty
        # trajectory), so `.get(key, 0)` returned None and the division below
        # raised TypeError. Coercing it to 0 would be worse than the crash: it
        # would publish "this run scored 0%" for a run that was never scored at
        # all, which is precisely the claim the reward ledger declines to make.
        # Unscored stays null, and the delivery bundle says so.
        rubric_pct = report.get("rubric_weights_percentage")
        score_data = {
            "model": report.get("model", run_model),
            "run_index": report.get("run_index", 1),
            "rubric_weights_percentage": rubric_pct,
            "total": len(rubric),
            "passed": sum(1 for r in rubric if _rubric_cleared(r)),
            "failed": sum(1 for r in rubric if not _rubric_cleared(r)),
            "reward": pct_to_reward(rubric_pct),
            "scored": rubric_pct is not None,
            "rubric": rubric,
            "judge_model": judge_tokens.get("model_name", ""),
            "judge_usage": report.get("judge_usage", {}),
        }
        _dump(ver_dst / "score.json", score_data)

    # Safety net: whatever else landed in the bundle (artifacts, logs, task
    # data), no host-local path may ship. This also catches future additions
    # to the bundle without anyone having to remember the masking rule.
    swept = mask_tree(dst)
    for p in swept:
        print(f"masked local paths in: {p.relative_to(dst)}")

    print(f"Done: {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reformat output/<task>/ into delivery_output/<task>/"
    )
    parser.add_argument("task_slug", nargs="?",
                        help="Task slug, e.g. bull-street-lot-expense-claim")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--tasks-dir", default="tasks")
    parser.add_argument("--delivery-dir", default="delivery_output")
    # The masking sweep on its own, over a directory that is already in its
    # final shape. harbor_to_output.py runs it as part of reshape, but two
    # stages write after that -- netaudit's internet_audit.json and finance's
    # receipt -- so run_task.sh calls this again once they are done. Also the
    # way to clean a tree reshaped before these rules covered it.
    parser.add_argument("--mask-only", metavar="DIR",
                        help="mask host-local paths under DIR and exit")
    args = parser.parse_args()

    if args.mask_only:
        root = Path(args.mask_only)
        if not root.is_dir():
            print(f"no such directory: {root}", file=sys.stderr)
            raise SystemExit(1)
        for p in mask_tree(root):
            print(f"masked local paths in: {p}")
        return

    if not args.task_slug:
        parser.error("task_slug is required unless --mask-only is given")

    base = Path(__file__).resolve().parent.parent
    make_delivery(
        task_slug=args.task_slug,
        output_dir=base / args.output_dir,
        tasks_dir=base / args.tasks_dir,
        delivery_dir=base / args.delivery_dir,
    )


if __name__ == "__main__":
    main()
