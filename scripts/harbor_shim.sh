# Sourced from ~/.zshrc. Makes every `harbor run …` land directly in
#
#     /Users/macbookpro/Documents/mcp-atlas/output/<task>/
#
# in the complex-mcp "harbor" layout (config/lock/result.json + summary.json,
# pass_summary.json, passk_summary.json, report.md, trajectory/Run_N/, .raw/).
# There is no separate jobs/ directory: Harbor is pointed at output/ with the
# task slug as the job name, and the HarborOutputPlugin reshapes the job in
# place when it finishes. A previous run of the same task is moved to
# output/.history/<task>__<timestamp>/ first, so nothing is lost.
#
#   harbor run --path tasks/xenon-atomic-cube --agent claude-code --model claude-opus-4-8
#
# Knobs (export before running):
#   HARBOR_OUTPUT_DIR=…        default <mcp-atlas repo>/output
#   HARBOR_OUTPUT_COPY_TO=…    optional extra mirror dir (default: none)
#   HARBOR_OUTPUT_OFF=1        bypass the shim entirely for one invocation
MCP_ATLAS_REPO="${MCP_ATLAS_REPO:-/Users/macbookpro/Documents/mcp-atlas}"

harbor() {
  if [[ "${1:-}" != "run" || -n "${HARBOR_OUTPUT_OFF:-}" ]]; then
    command harbor "$@"
    return
  fi
  local out_root="${HARBOR_OUTPUT_DIR:-$MCP_ATLAS_REPO/output}"

  # auth: Harbor's claude-code agent + the LLM judge need a token
  if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" && -z "${ANTHROPIC_API_KEY:-}" ]]; then
    local tok
    tok="$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null \
      | python3 -c 'import sys,json; print(json.load(sys.stdin)["claudeAiOauth"]["accessToken"])' 2>/dev/null)"
    [[ -n "$tok" ]] && export CLAUDE_CODE_OAUTH_TOKEN="$tok"
  fi

  # scan args: task path, and which flags the user already gave
  local has_plugin=0 has_yes=0 has_jobs_dir=0 has_job_name=0 task_path="" a prev=""
  for a in "$@"; do
    [[ "$a" == *harbor_output_plugin* ]] && has_plugin=1
    [[ "$a" == "-y" || "$a" == "--yes" ]] && has_yes=1
    [[ "$a" == "--jobs-dir" || "$a" == "-o" ]] && has_jobs_dir=1
    [[ "$a" == "--job-name" ]] && has_job_name=1
    [[ "$prev" == "--path" || "$prev" == "-p" ]] && task_path="$a"
    [[ "$a" == --path=* ]] && task_path="${a#--path=}"
    prev="$a"
  done

  local -a extra=()
  (( ! has_plugin )) && extra+=(--plugin "adapters.mcp_atlas.harbor_output_plugin:HarborOutputPlugin")
  (( ! has_yes ))    && extra+=(-y)   # auto-accept the verifier-env passthrough prompt

  if (( ! has_jobs_dir )); then
    extra+=(--jobs-dir "$out_root")
    if (( ! has_job_name )) && [[ -n "$task_path" ]]; then
      local slug; slug="$(basename "${task_path%/}")"
      if [[ -d "$out_root/$slug" ]]; then
        mkdir -p "$out_root/.history"
        local stamp; stamp="$(date +%Y%m%d-%H%M%S)"
        mv "$out_root/$slug" "$out_root/.history/${slug}__${stamp}"
        echo "[harbor-output] previous run moved to output/.history/${slug}__${stamp}/"
      fi
      extra+=(--job-name "$slug")
    fi
  fi

  PYTHONPATH="${MCP_ATLAS_REPO}${PYTHONPATH:+:$PYTHONPATH}" command harbor "$@" "${extra[@]}"
}
