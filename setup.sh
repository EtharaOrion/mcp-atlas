#!/bin/bash
set -e

ECR_HOST="426628337772.dkr.ecr.ap-south-1.amazonaws.com"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== [1/4] Installing prerequisites ==="

# Homebrew is macOS-only here. Unguarded, this block INSTALLED Homebrew on an
# Amazon Linux box and then reinstalled docker over a working docker, on a
# machine whose only actual problem was a stale harbor. A Linux host is expected
# to arrive with these already present, so say what is missing and carry on
# rather than trying to provision it.
if [ "$(uname -s)" = "Darwin" ]; then
    if ! command -v brew &> /dev/null; then
        echo "Homebrew not found. Installing..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add Homebrew to PATH for this shell (Apple Silicon default location)
        eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true
    fi

    # Core tools
    brew install -q \
        git \
        python@3.12 \
        awscli \
        docker \
        docker-compose \
        docker-credential-helper-ecr \
        jq \
        pipx \
        codex 2>&1 | tail -3 || true
else
    echo "Non-macOS host ($(uname -s)): skipping the Homebrew block."
    missing=""
    for c in git python3 aws docker jq codex docker-credential-ecr-login; do
        command -v "$c" >/dev/null 2>&1 || missing="$missing $c"
    done
    command -v uv >/dev/null 2>&1 || command -v pipx >/dev/null 2>&1 || missing="$missing uv-or-pipx"
    if [ -n "$missing" ]; then
        echo "  MISSING, install with the system package manager:$missing"
    else
        echo "  all expected host tools are present"
    fi
fi

# harbor runs the trials and scripts/patch_harbor.py refuses to start without
# it; claude is the agent CLI the rubric can fall back to. The pin and the
# uv/pipx choice both live in scripts/lib/harbor.sh so run_task.sh can quote the
# same command back when it finds the wrong version.
# shellcheck source=scripts/lib/harbor.sh
. "$REPO_ROOT/scripts/lib/harbor.sh"
harbor_install || true
if ! command -v claude &> /dev/null; then
    curl -fsSL https://claude.ai/install.sh | bash || true
fi

echo ""
echo "=== [2/4] Setting up Python venv ==="

if [ ! -d "$REPO_ROOT/.venv" ]; then
    # python3.12 is the brew name; a Linux host may only have python3.
    if command -v python3.12 >/dev/null 2>&1; then
        python3.12 -m venv "$REPO_ROOT/.venv"
    else
        python3 -m venv "$REPO_ROOT/.venv"
    fi
fi

# A venv created by `uv venv` ships WITHOUT pip. Activating it and calling pip
# then dies with "pip: command not found", and set -e takes the rest of setup
# down with it -- ECR wiring and the verification block never run. uv needs no
# pip and is the documented prerequisite, so prefer it; otherwise drive the
# venv's own interpreter, which does not depend on `pip` being on PATH.
if command -v uv >/dev/null 2>&1; then
    VIRTUAL_ENV="$REPO_ROOT/.venv" uv pip install -q -r "$REPO_ROOT/requirements.txt"
else
    "$REPO_ROOT/.venv/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
    "$REPO_ROOT/.venv/bin/python" -m pip install --quiet --upgrade pip
    "$REPO_ROOT/.venv/bin/python" -m pip install --quiet -r "$REPO_ROOT/requirements.txt"
fi

echo "Python venv ready at $REPO_ROOT/.venv"

echo ""
echo "=== [3/4] Wiring ECR credential helper ==="

# credHelpers names a BINARY (docker-credential-ecr-login). The macOS branch
# installs it via brew; a Linux host has to supply it, and without it every ECR
# pull fails with "docker-credential-ecr-login: executable file not found" long
# after setup reported success.
if ! command -v docker-credential-ecr-login >/dev/null 2>&1; then
    echo "  WARNING: docker-credential-ecr-login is NOT installed."
    echo "           ECR pulls will fail until it is. Install it with:"
    if   command -v dnf     >/dev/null 2>&1; then echo "             sudo dnf install -y amazon-ecr-credential-helper"
    elif command -v yum     >/dev/null 2>&1; then echo "             sudo yum install -y amazon-ecr-credential-helper"
    elif command -v apt-get >/dev/null 2>&1; then echo "             sudo apt-get install -y amazon-ecr-credential-helper"
    else echo "             (see github.com/awslabs/amazon-ecr-credential-helper)"
    fi
fi

python3 <<PY
import json, pathlib
p = pathlib.Path.home() / ".docker" / "config.json"
p.parent.mkdir(exist_ok=True)
d = json.loads(p.read_text()) if p.exists() else {}
d.setdefault("credHelpers", {})
d["credHelpers"]["${ECR_HOST}"] = "ecr-login"
# Remove empty auth entry if present (blocks credential helper lookup)
if "auths" in d and "${ECR_HOST}" in d["auths"]:
    if not d["auths"]["${ECR_HOST}"]:
        del d["auths"]["${ECR_HOST}"]
p.write_text(json.dumps(d, indent=2))
print(f"Updated {p}")
PY

echo ""
echo "=== [4/4] Verifying installed tools ==="

check() {
    local name="$1" cmd="$2"
    if command -v "$cmd" &> /dev/null; then
        echo "  ✓ $name: $($cmd --version 2>&1 | head -1)"
    else
        echo "  ✗ $name: MISSING"
    fi
}
check "docker"                     docker
check "docker-credential-ecr-login" docker-credential-ecr-login
check "aws"                        aws
check "python3.12"                 python3.12
check "brew"                       brew
check "harbor"                     harbor
check "codex"                      codex
check "claude"                     claude

echo ""
echo "==============================================================="
echo "Setup complete."
echo ""
echo "Manual next steps:"
echo "  1. Edit .env with:"
echo "       AWS_ACCESS_KEY_ID=..."
echo "       AWS_SECRET_ACCESS_KEY=..."
echo "       AWS_DEFAULT_REGION=ap-south-1"
echo "     plus any LLM credentials (Claude/Codex/GLM)"
echo ""
echo "  2. Log into the model accounts:"
echo "       claude login"
echo "       codex login"
echo ""
echo "  3. Test ECR access (should print 'Downloaded'):"
echo "       set -a; source .env; set +a"
echo "       docker pull ${ECR_HOST}/yuji:judge-1.0.0"
echo ""
echo "  4. Run a task:"
echo "       scripts/run_task.sh tasks/<bundle>"
echo "==============================================================="
