/**
 * Shared types for MCP agent evaluation
 */

import { z } from 'zod';

// ============================================================================
// Tool Definitions
// ============================================================================

export const ToolCallDefinitionSchema = z.object({
  type: z.literal('function'),
  function: z.object({
    name: z.string(),
    description: z.string(),
    parameters: z
      .object({
        type: z.string(),
      })
      .passthrough(),
    strict: z.boolean().optional(),
  }),
});

export type ToolCallDefinition = z.infer<typeof ToolCallDefinitionSchema>;

export const ToolCallSchema = z.object({
  id: z.string(),
  type: z.literal('function'),
  function: z.object({
    name: z.string(),
    arguments: z.string(),
  }),
});

export type ToolCall = z.infer<typeof ToolCallSchema>;

export const ToolCallOutputContentItemSchema = z.union([
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

export const ToolCallOutputContentSchema = z.array(ToolCallOutputContentItemSchema);

export type ToolCallOutputContentItem = z.infer<typeof ToolCallOutputContentItemSchema>;
export type ToolCallOutputContent = z.infer<typeof ToolCallOutputContentSchema>;

export interface ToolCallOutput {
  content: ToolCallOutputContent;
  isError: boolean;
  metadata?: Record<string, any>;
}

// ============================================================================
// Message Schemas
// ============================================================================

export const SystemMessageSchema = z.object({
  role: z.literal('system'),
  content: z.string(),
});
export type SystemMessage = z.infer<typeof SystemMessageSchema>;

export const UserMessageSchema = z.object({
  role: z.literal('user'),
  content: z.string(),
});
export type UserMessage = z.infer<typeof UserMessageSchema>;

export const AssistantMessageSchema = z.object({
  role: z.literal('assistant'),
  content: z.string().nullable().optional(),
  tool_calls: z.array(ToolCallSchema).nullable().optional(),
  reasoning_content: z.string().nullable().optional(),
});
export type AssistantMessage = z.infer<typeof AssistantMessageSchema>;

export const ToolCallOutputMessageSchema = z.object({
  role: z.literal('tool'),
  content: ToolCallOutputContentSchema,
  tool_call_id: z.string(),
  metadata: z.record(z.any()).optional(),
});
export type ToolCallOutputMessage = z.infer<typeof ToolCallOutputMessageSchema>;

export const MessageSchema = z.union([
  SystemMessageSchema,
  UserMessageSchema,
  AssistantMessageSchema,
  ToolCallOutputMessageSchema,
]);
export type Message = z.infer<typeof MessageSchema>;

// ============================================================================
// Trajectory Schemas — see schema.ts for the source of truth / doc comment.
// ============================================================================

export const TrajectoryStepMetricsSchema = z.object({
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
  total_tokens: z.number().optional(),
  cost_usd: z.number().nullable().optional(),
});
export type TrajectoryStepMetrics = z.infer<typeof TrajectoryStepMetricsSchema>;

export const TrajectoryStepSchema = z.object({
  step_id: z.number(),
  timestamp: z.string(),
  message: AssistantMessageSchema,
  tool_results: z.array(ToolCallOutputMessageSchema).optional(),
  metrics: TrajectoryStepMetricsSchema.optional(),
  extra: z.record(z.string(), z.any()).optional(),
});
export type TrajectoryStep = z.infer<typeof TrajectoryStepSchema>;

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
export type RunTrajectory = z.infer<typeof RunTrajectorySchema>;

// ============================================================================
// Tool Definition Schema (MCP)
// ============================================================================

export const ToolDefinitionSchema = z
  .object({
    name: z.string(),
    title: z.string().optional(),
    description: z.string(),
    inputSchema: z.any(),
    outputSchema: z.any().optional(),
    annotations: z.array(z.string()).optional(),
    server: z.string().optional(),
    disabled: z.boolean().optional(),
  })
  .passthrough();

export type ToolDefinition = z.infer<typeof ToolDefinitionSchema>;
