import { z } from 'zod';

// ============================================================================
// Message Schemas
// ============================================================================

const TextPartSchema = z.object({ type: z.literal('text'), text: z.string() });
const ImageUrlPartSchema = z.object({
  type: z.literal('image_url'),
  image_url: z.object({ url: z.string(), detail: z.string().optional() }),
});
const InputAudioPartSchema = z.object({
  type: z.literal('input_audio'),
  input_audio: z.object({ data: z.string(), format: z.string() }),
});
const ContentPartSchema = z.discriminatedUnion('type', [
  TextPartSchema, ImageUrlPartSchema, InputAudioPartSchema,
]);
export const MessageContentSchema = z.union([z.string(), z.array(ContentPartSchema)]);

export const SystemMessageSchema = z.object({
  role: z.literal('system'),
  content: MessageContentSchema,
});

const UserMessageSchema = z.object({
  role: z.literal('user'),
  content: MessageContentSchema,
});

export const AssistantMessageSchema = z.object({
  role: z.literal('assistant'),
  content: z.string().nullish(),
  tool_calls: z
    .array(
      z.object({
        id: z.string(),
        type: z.literal('function'),
        function: z.object({
          name: z.string(),
          arguments: z.string(),
        }),
      }),
    )
    .nullish(),
  reasoning_content: z.string().nullish(),
});

const ToolCallOutputContentItemSchema = z.union([
  z.object({
    type: z.literal('text'),
    text: z.string(),
  }),
  z.object({
    type: z.literal('image'),
    image_url: z.object({
      url: z.string(),
    }),
  }),
]);

const ToolCallOutputMessageSchema = z.object({
  role: z.literal('tool'),
  tool_call_id: z.string(),
  content: z.array(ToolCallOutputContentItemSchema).default([]),
  metadata: z.record(z.any()).optional(),
});

export const MessageSchema = z.union([
  SystemMessageSchema,
  UserMessageSchema,
  AssistantMessageSchema,
  ToolCallOutputMessageSchema,
]);

// ============================================================================
// Trajectory Schemas
//
// Additive, agent-agnostic run record emitted alongside the existing flat
// `{type:'message', data}` event stream (as one more `{type:'trajectory',
// data}` entry) — old consumers (run_eval.py's `type == "message"` filter)
// are unaffected; new consumers can read the richer per-step/token/cost view.
// ============================================================================

export const TrajectoryStepMetricsSchema = z.object({
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
  total_tokens: z.number().optional(),
  // Best-effort — only populated when the endpoint reports spend (e.g. a
  // LiteLLM proxy). Plain OpenAI-compatible endpoints leave this undefined.
  cost_usd: z.number().nullable().optional(),
});

export const TrajectoryStepSchema = z.object({
  step_id: z.number(),
  timestamp: z.string(),
  // Carries reasoning_content automatically when the model/provider returns
  // it — no separate field needed, it's already on AssistantMessageSchema.
  message: AssistantMessageSchema,
  tool_results: z.array(ToolCallOutputMessageSchema).optional(),
  metrics: TrajectoryStepMetricsSchema.optional(),
});

export const RunTrajectorySchema = z.object({
  schema_version: z.literal('mcp-atlas-trajectory-v1'),
  session_id: z.string(),
  task_id: z.string(),
  agent: z.object({
    name: z.literal('litellm'),
    model_name: z.string(),
  }),
  final_metrics: z.object({
    total_prompt_tokens: z.number(),
    total_completion_tokens: z.number(),
    total_cost_usd: z.number().nullable(),
    total_steps: z.number(),
  }),
  steps: z.array(TrajectoryStepSchema),
});

// ============================================================================
// Request / Response Schemas
// ============================================================================

export const RunAgentAPIRequestBodySchema = z.object({
  image: z.string().optional(),
  tags: z.record(z.string(), z.string()).optional(),
  model: z.string(),
  messages: z.array(MessageSchema),
  enabledTools: z.array(z.string()),
  max_turns: z.number().optional(),
  strategy: z.string().optional(),
  task_id: z.string().optional(),
  llm_base_url: z.string().optional(),
  extra_llm_params: z.record(z.string(), z.any()).optional(),
  // 'compact' is the historical spelling and keeps working; 'headroom' is the
  // same behaviour under a clearer name; 'off' is an explicit off switch,
  // identical to omitting the field.
  context_window_management: z.enum(['compact', 'headroom', 'off']).optional(),
  // Headroom knobs. Compaction fires once the projected prompt exceeds
  // context_window_tokens * condenser_token_fraction — by default the full
  // 1M window. The first condenser_keep_first messages are never truncated.
  // Validated rather than clamped: a typo'd fraction (80 for 0.8) would push
  // the threshold past the window and silently disable headroom, so it is
  // rejected at the boundary instead. 0 is allowed and means "no budget",
  // which falls back to the turn-count backstop.
  context_window_tokens: z.number().int().nonnegative().optional(),
  condenser_token_fraction: z.number().min(0).max(1).optional(),
  condenser_keep_first: z.number().int().nonnegative().optional(),
  // Condense older turns into an LLM summary instead of discarding them
  // (default true), and optionally use a cheaper model to do it.
  condenser_summarize: z.boolean().optional(),
  condenser_model: z.string().optional(),
  tool_output_cap: z.number().optional(),
  max_tool_calls: z.number().optional(),
});

export const CallToolAPIRequestBodySchema = z.object({
  image: z.string(),
  tags: z.record(z.string(), z.string()).optional(),
  toolName: z.string(),
  toolArgs: z.record(z.string(), z.any()),
});

export const CallToolResponseSchema = z.object({
  content: z.array(ToolCallOutputContentItemSchema).default([]),
  isError: z.boolean().default(false),
});

// ============================================================================
// Sandbox tool-disabling registry
// ============================================================================

export const SandboxToolsConfigSchema = z.array(
  z.object({
    image: z.string(),
    disabledTools: z.array(z.string()),
  }),
);
