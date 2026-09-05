/**
 * Configuration for the MCP evaluation server
 */

export const config = {
  // Server configuration
  port: process.env.PORT || 3001,

  // LLM proxy configuration (any LiteLLM-compatible endpoint)
  llmBaseUrl: process.env.LLM_BASE_URL || '',
  llmApiKeys: (process.env.LLM_API_KEY || '').split(',').map(k => k.trim()).filter(Boolean),
  get llmApiKey(): string {
    const keys = config.llmApiKeys;
    return keys[Math.floor(Math.random() * keys.length)];
  },

  // MCP sandbox URL (e.g. http://localhost:1984 when running agent-environment locally)
  mcpSandboxUrl: process.env.MCP_SANDBOX_URL || 'http://localhost:1984',

  // Logging configuration
  logLevel: process.env.LOG_LEVEL || 'info',

  // Request timeouts (ms). Uncapped by default so heavy-reasoning models and
  // large tool payloads are never cut off mid-run. 0 means no timeout — for
  // axios that is its native "wait forever", and promiseWithTimeout skips the
  // race entirely. Set a positive value to reimpose a cap.
  toolCallTimeoutMs: Number(process.env.TOOL_CALL_TIMEOUT_MS) || 0,
  listToolsTimeoutMs: Number(process.env.LIST_TOOLS_TIMEOUT_MS) || 0,
  llmTimeoutMs: Number(process.env.LLM_TIMEOUT_MS) || 0,

  // Context-window headroom defaults. Compaction is triggered by measured token
  // usage against this window, not by a turn count, and only runs at all when a
  // request asks for context_window_management. Sized for a 1M-token window,
  // with the trigger at the window itself: the conversation is compacted once
  // the projected prompt passes 1_000_000 tokens. Set CONDENSER_TOKEN_FRACTION
  // below 1 to compact earlier and leave margin for the completion.
  contextWindowTokens: Number(process.env.CONTEXT_WINDOW_TOKENS) || 1_000_000,
  condenserTokenFraction: Number(process.env.CONDENSER_TOKEN_FRACTION) || 1.0,
  condenserKeepFirst: Number(process.env.CONDENSER_KEEP_FIRST) || 2,
  // Condense older turns with an LLM summary rather than discarding them. On
  // by default when context management is requested (mirroring goku), because
  // a discarded tool result is unrecoverable while a summary keeps the
  // findings. Costs one extra LLM call per compaction — set
  // CONDENSER_SUMMARIZE=false for the cheaper truncate-and-drop behaviour.
  condenserSummarize: (process.env.CONDENSER_SUMMARIZE || 'true').toLowerCase() !== 'false',
}

// Validate required environment variables
if (config.llmApiKeys.length === 0) {
  throw new Error('LLM_API_KEY environment variable is required')
}
if (!config.llmBaseUrl) {
  throw new Error('LLM_BASE_URL environment variable is required')
}
