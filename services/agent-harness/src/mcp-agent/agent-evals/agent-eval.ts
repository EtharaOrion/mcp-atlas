import { randomUUID } from 'node:crypto';
import type {
  ToolCallDefinition,
  ToolCall,
  Message,
  ToolDefinition,
  ToolCallOutputMessage,
  TrajectoryStep,
  RunTrajectory,
} from '../types';
import {
  AssistantMessageSchema,
  CallToolResponseSchema,
  RunAgentAPIRequestBodySchema,
  CallToolAPIRequestBodySchema,
} from '../schema';
import { getAgentCompletionStrategy, type BaseCompletionResult } from './completion-strategy';
import { MCPClient, createMCPClient } from '../helpers/mcp-client';
import { SandboxMCPClient } from '../helpers/mcp-client/sandbox-client';
import {
  applySummary,
  buildSummaryRequest,
  compactToBudget,
  isHeadroomEnabled,
  measurePrompt,
  planCompaction,
  projectTokensAfter,
  resolveThresholdTokens,
  type ContextWindowManagement,
} from './context-headroom';
import { logger } from '../../logger';
import { config } from '../../config';
import { z } from 'zod';
const DEFAULT_MAX_TURNS = 256;
const DEFAULT_MAX_TOOL_CALLS = 100;

type AgentOutput =
  | { type: 'message'; data: Message; usage?: Record<string, any>; finish_reason?: string; extra?: Record<string, any>; timestamp?: string }
  | { type: 'trajectory'; data: RunTrajectory }
  | { type: 'error'; data: any };

interface RunAgentAPIOptions {
  mcpClient: MCPClient;
  model: string;
  messages: Message[];
  maxTurns?: number;
  strategy?: string;
  llmBaseUrl?: string;
  extraLlmParams?: Record<string, any>;
  taskId?: string;
  contextWindowManagement?: ContextWindowManagement;
  contextWindowTokens?: number;
  condenserTokenFraction?: number;
  condenserKeepFirst?: number;
  /** Condense older turns with an LLM summary instead of discarding them. */
  condenserSummarize?: boolean;
  /** Model used for that summary; defaults to the agent's own model. */
  condenserModel?: string;
  toolOutputCap?: number;
  maxToolCalls?: number;
}

/**
 * Cap tool result content to a maximum number of characters.
 * Returns the content array with text truncated if needed.
 */
function capToolContent(content: any[], cap: number): any[] {
  const fullText = content.map((c: any) => c.text || '').join('');
  if (fullText.length <= cap) return content;
  const truncatedText = fullText.slice(0, cap) + `\n\n[Tool output truncated to ${cap} chars. Original was ${fullText.length} chars.]`;
  // Cap the text, keep everything else. An image is not text volume and cannot
  // be reconstructed from a note about how many characters were cut, so the
  // cap must not be the thing that deletes it.
  const preserved = content.filter((c: any) => c?.type !== 'text');
  return [{ type: 'text', text: truncatedText }, ...preserved];
}

function* handleCompletionError(error: any, mcpClient: MCPClient): Generator<AgentOutput> {
  if (mcpClient instanceof SandboxMCPClient) {
    logger.error('Model Create completion or parsing failed', {
      message: error.message || String(error),
      stack: error.stack || null,
      info: mcpClient.sandboxInfo,
      responseData: error.response?.data || null,
      responseStatus: error.response?.status || null,
    });
  } else {
    logger.error('Model Create Completion or Parsing Failed', {
      message: error.message || String(error),
      stack: error.stack || null,
      responseData: error.response?.data || null,
      responseStatus: error.response?.status || null,
    });
  }

  yield {
    type: 'error' as const,
    data: {
      message: error.message || String(error),
      serverResponse: error.response?.data || null,
    },
  };
}

/**
 * Simply agent loop that keeps calling tools until the model decides there are no more tools to call.
 */
async function* runMcpAgent({
  model,
  messages,
  mcpClient,
  maxTurns = DEFAULT_MAX_TURNS,
  strategy,
  llmBaseUrl,
  extraLlmParams,
  taskId,
  contextWindowManagement,
  contextWindowTokens = config.contextWindowTokens,
  condenserTokenFraction = config.condenserTokenFraction,
  condenserKeepFirst = config.condenserKeepFirst,
  condenserSummarize = config.condenserSummarize,
  condenserModel,
  toolOutputCap,
  maxToolCalls = DEFAULT_MAX_TOOL_CALLS,
}: RunAgentAPIOptions): AsyncGenerator<AgentOutput, void, unknown> {
  // Log agent loop configuration
  const headroomEnabled = isHeadroomEnabled(contextWindowManagement);
  const sandboxInfo = mcpClient instanceof SandboxMCPClient ? mcpClient.sandboxInfo : null;
  logger.info('=== STARTING AGENT LOOP ===', {
    taskId,
    model,
    strategy: strategy || 'default (litellm)',
    maxTurns,
    maxToolCalls,
    toolOutputCap,
    contextWindowManagement: contextWindowManagement ?? 'off (default)',
    contextWindowTokens: headroomEnabled ? contextWindowTokens : null,
    condenserTokenFraction: headroomEnabled ? condenserTokenFraction : null,
    condenserKeepFirst: headroomEnabled ? condenserKeepFirst : null,
    condenserSummarize: headroomEnabled ? condenserSummarize : null,
    condenserModel: headroomEnabled && condenserSummarize ? (condenserModel || model) : null,
    compactionThresholdTokens: headroomEnabled
      ? resolveThresholdTokens(contextWindowTokens, condenserTokenFraction)
      : null,
    messageCount: messages.length,
    sandboxId: sandboxInfo?.sandboxId,
    sandboxTags: sandboxInfo?.sandboxTags,
  });

  const tools = await mcpClient.listTools();
  logger.info('Available tools loaded', { toolCount: tools.length });

  // Reset sandbox state disabled — the agent-environment image
  // does not implement /reset-state (returns 404), causing noisy errors.
  // Re-enable if the Docker image adds this endpoint.
  const transformedTools = _transformToolCalls(tools);
  const allMessages: Message[] = [...messages];

  // Track whether the loop exhausted maxTurns without a natural break.
  // Set to false in every explicit break path; remains true only if the
  // for-loop condition (i < maxTurns) is what ended the loop.
  let reachedMaxTurns = true;
  let totalToolCalls = 0;
  let reachedMaxToolCalls = false;

  // Trajectory bookkeeping — one TrajectoryStep per turn (assistant message +
  // the tool results it produced), assembled alongside the existing
  // 'message' event stream and emitted as a single 'trajectory' event at the
  // end. See schema.ts's Trajectory* schemas for field docs.
  const sessionId = randomUUID();
  const trajectorySteps: TrajectoryStep[] = [];
  let stepCounter = 0;
  let totalPromptTokens = 0;
  let totalCompletionTokens = 0;
  let totalCostUsd: number | null = null;
  let costTracked = false;
  // Summarizer spend is tracked apart from the agent's, the way goku gives the
  // condenser its own usage_id: it is overhead of context management, not work
  // the agent did, and conflating them makes both numbers unreadable.
  let summarizerPromptTokens = 0;
  let summarizerCompletionTokens = 0;
  let summarizerCalls = 0;

  // Headroom bookkeeping: the last measured prompt size and how many messages
  // have been appended since, so the next prompt can be projected from a real
  // measurement rather than re-estimated from scratch every turn.
  let lastPromptTokens: number | undefined;
  let lastPromptChars: number | undefined;
  let lastPromptImages: number | undefined;
  let messageCountAtLastCall = 0;

  for (let i = 0; i < maxTurns; i++) {
    // Check tool call limit before next LLM call
    if (maxToolCalls && totalToolCalls >= maxToolCalls) {
      reachedMaxTurns = false;
      reachedMaxToolCalls = true;
      break;
    }
    logger.info(`[${taskId}] Turn ${i + 1}/${maxTurns}`, { messageCount: allMessages.length, totalToolCalls });
    const turnTimestamp = new Date().toISOString();
    let assistantMessage;
    let turnUsage: BaseCompletionResult['usage'];
    let lastFinishReason: string | undefined;
    let lastExtra: Record<string, any> | undefined;
    // How many messages the prompt we are about to send contains. Committed as
    // the headroom anchor only if this call comes back with usage.
    let promptMessageCount = allMessages.length;
    let promptChars = 0;
    let promptImages = 0;
    try {
      // Get the appropriate strategy based on model and strategy parameter
      const completionStrategy = getAgentCompletionStrategy(model, strategy, llmBaseUrl);

      // Context-window headroom — compaction fires on the projected token size
      // of the prompt we are about to send, not on a turn count, so it stays
      // idle until the conversation actually approaches the model's window.
      let messagesToSend = allMessages;
      if (headroomEnabled) {
        // Try the summary first when enabled: computing a reduction only to
        // throw it away costs a full pass over the conversation.
        const trySummaryFirst = condenserSummarize;
        const plan = planCompaction(allMessages, {
          skipReduction: trySummaryFirst,
          turnIndex: i,
          lastPromptTokens,
          lastPromptChars,
          lastPromptImages,
          messageCountAtLastCall,
          contextWindowTokens,
          condenserTokenFraction,
          keepFirst: condenserKeepFirst,
        });
        const decision = plan.decision;
        let outcome = plan.outcome;
        messagesToSend = plan.messagesToSend;
        let summarized = false;

        // Summarize before falling back to discarding. One LLM call turns the
        // older turns into a carried-forward brief, so the findings survive
        // even though the raw text does not. Any failure drops straight back
        // to the truncate/drop result already computed above — headroom
        // protection must never depend on a second network call succeeding.
        if (trySummaryFirst && decision.shouldCompact && decision.trigger === 'token-budget') {
          const summaryRequest = buildSummaryRequest(allMessages, condenserKeepFirst);
          if (summaryRequest) {
            try {
              const summarizerModel = condenserModel || model;
              const summaryResult = await getAgentCompletionStrategy(summarizerModel, strategy, llmBaseUrl)
                .createCompletion({
                  model: summarizerModel,
                  messages: summaryRequest.messages,
                  tools: [],
                  extraLlmParams,
                });
              const summaryText = typeof (summaryResult.message as any)?.content === 'string'
                ? ((summaryResult.message as any).content as string).trim()
                : '';
              if (summaryText.length > 0) {
                messagesToSend = applySummary(allMessages, summaryText, summaryRequest);
                summarized = true;
                summarizerCalls++;
                if (summaryResult.usage) {
                  summarizerPromptTokens += summaryResult.usage.prompt_tokens ?? 0;
                  summarizerCompletionTokens += summaryResult.usage.completion_tokens ?? 0;
                }
                logger.info(
                  `[${taskId}] Condensed ${summaryRequest.reducibleToolIndices.length} tool result(s) ` +
                  `into a ${summaryText.length}-char summary via ${summarizerModel}`,
                );
              } else {
                logger.warn(`[${taskId}] Summarizer returned nothing; falling back to truncation`);
              }
            } catch (summaryError: any) {
              logger.warn(
                `[${taskId}] Summarizer call failed, falling back to truncation: ` +
                `${summaryError?.message || String(summaryError)}`,
              );
            }
          }
        }

        // Summary skipped, impossible or failed — run the reduction the plan
        // deferred, so headroom protection never hinges on a second network
        // call succeeding.
        if (!summarized && trySummaryFirst && decision.shouldCompact && decision.trigger === 'token-budget') {
          outcome = compactToBudget(allMessages, {
            promptTokensBefore: decision.promptTokensBefore,
            thresholdTokens: decision.thresholdTokens!,
            keepFirst: condenserKeepFirst,
            charsPerToken: decision.charsPerToken,
          });
          if (outcome.changed) messagesToSend = outcome.messages;
        }

        // Reported and persisted together: any reduction we apply is always
        // logged, so context is never dropped from the conversation silently.
        if (messagesToSend !== allMessages) {
          // Text only — image payloads are billed per item, so counting their
          // bytes here would make every saving look negligible beside them.
          const originalChars = measurePrompt(allMessages).textChars;
          const compactedChars = measurePrompt(messagesToSend).textChars;
          const saved = originalChars - compactedChars;
          // The backstop path has no outcome to report, so project its result
          // the same way compactToBudget does.
          // Measured from what we are actually sending, so the number always
          // describes the path that ran rather than the one that did not.
          const estimatedTokensAfter = summarized || !outcome
            ? projectTokensAfter(decision.promptTokensBefore, saved, decision.charsPerToken)
            : outcome.estimatedTokensAfter;
          logger.info(
            `[${taskId}] Compact (${summarized ? 'summary' : 'truncate'}, ${decision.trigger}, ` +
            `usage from ${decision.usageSource}): ` +
            `${decision.promptTokensBefore} → ~${estimatedTokensAfter} tokens ` +
            `vs threshold ${decision.thresholdTokens ?? 'n/a'}/${decision.contextWindowTokens ?? 'n/a'}; ` +
            `${originalChars} → ${compactedChars} chars (saved ${saved}, ${(saved/originalChars*100).toFixed(1)}%)`,
          );
          if (!summarized && outcome && outcome.droppedCount > 0) {
            // Never discard context silently — name what was thrown away.
            logger.warn(`[${taskId}] Compact dropped ${outcome.droppedCount} tool result(s) entirely`, {
              toolCallIds: outcome.droppedToolCallIds,
            });
          }
          if (decision.thresholdTokens !== null && estimatedTokensAfter > decision.thresholdTokens) {
            logger.warn(`[${taskId}] Compact could not get under ${decision.thresholdTokens} tokens; sending ~${estimatedTokensAfter}`);
          }
          yield {
            type: 'compaction' as any,
            data: {
              turn: i + 1,
              trigger: decision.trigger,
              // 'summary' = older turns condensed by an LLM call, findings kept.
              // 'truncate' = they were cut down and, if needed, discarded.
              method: summarized ? 'summary' : 'truncate',
              summarizerCalls,
              summarizerPromptTokens,
              summarizerCompletionTokens,
              usageSource: decision.usageSource,
              // Calibrated from the provider's own accounting once a turn has
              // reported usage; the CHARS_PER_TOKEN default until then.
              charsPerToken: Number(decision.charsPerToken.toFixed(3)),
              promptTokensBefore: decision.promptTokensBefore,
              thresholdTokens: decision.thresholdTokens,
              contextWindowTokens: decision.contextWindowTokens,
              estimatedTokensAfter,
              keepFirst: condenserKeepFirst,
              capApplied: summarized ? null : outcome?.capApplied ?? null,
              truncatedResults: summarized ? 0 : outcome?.truncatedCount ?? null,
              droppedResults: summarized ? 0 : outcome?.droppedCount ?? 0,
              droppedToolCallIds: summarized ? [] : outcome?.droppedToolCallIds ?? [],
              // False when even the tightest reduction could not reach the
              // threshold — the floor is keepFirst plus the turns we keep whole.
              fitsThreshold: decision.thresholdTokens === null
                ? null
                : estimatedTokensAfter <= decision.thresholdTokens,
              originalChars,
              compactedChars,
              savedChars: saved,
              savedPct: originalChars > 0 ? Math.round(saved / originalChars * 100) : 0,
            },
          };

          // Persist the reduction: the compacted history becomes the running
          // conversation, so the prompt_tokens we measure next turn describes
          // what allMessages actually holds and the projection stays honest.
          // The trajectory keeps its own references to the untouched originals.
          if (messagesToSend.length === allMessages.length) {
            for (let k = 0; k < allMessages.length; k++) allMessages[k] = messagesToSend[k];
          } else {
            allMessages.length = 0;
            for (const m of messagesToSend) allMessages.push(m);
          }
          messagesToSend = allMessages;
        } else if (decision.shouldCompact) {
          // Over budget with nothing reducible — an oversized opening prompt,
          // or a single tool result larger than the window. Silence here would
          // be the worst case: the call goes out doomed and fails at the
          // provider with an opaque error. Say so instead.
          logger.warn(
            `[${taskId}] Over context budget and nothing could be reduced: ` +
            `~${decision.promptTokensBefore} tokens vs threshold ${decision.thresholdTokens} ` +
            `(window ${decision.contextWindowTokens}). Everything eligible is inside keepFirst ` +
            `(${condenserKeepFirst}) or the last ${2} turns. Consider tool_output_cap.`,
          );
          yield {
            type: 'compaction' as any,
            data: {
              turn: i + 1,
              trigger: decision.trigger,
              usageSource: decision.usageSource,
              charsPerToken: Number(decision.charsPerToken.toFixed(3)),
              promptTokensBefore: decision.promptTokensBefore,
              thresholdTokens: decision.thresholdTokens,
              contextWindowTokens: decision.contextWindowTokens,
              estimatedTokensAfter: decision.promptTokensBefore,
              keepFirst: condenserKeepFirst,
              capApplied: null,
              truncatedResults: 0,
              droppedResults: 0,
              droppedToolCallIds: [],
              fitsThreshold: false,
              // Nothing was reduced, so there is no before/after to report.
              originalChars: null,
              compactedChars: null,
              savedChars: 0,
              savedPct: 0,
              reason: 'nothing-reducible',
            },
          };
        }
      }

      // Read back what we actually send: its message count anchors the next
      // projection, and its char size calibrates chars-per-token against the
      // prompt_tokens the provider bills for it. Only when headroom is on —
      // measuring serializes the whole conversation, and a caller who never
      // asked for compaction must not pay that on every turn.
      if (headroomEnabled) {
        promptMessageCount = messagesToSend.length;
        const sent = measurePrompt(messagesToSend);
        promptChars = sent.textChars;
        promptImages = sent.imageCount;
      }

      // Retry on transient errors (503, 429, network errors) up to 3 times
      let result;
      const MAX_LLM_RETRIES = 3;
      for (let retry = 0; retry < MAX_LLM_RETRIES; retry++) {
        try {
          result = await completionStrategy.createCompletion({
            model,
            messages: messagesToSend,
            tools: transformedTools,
            extraLlmParams,
          });
          break;
        } catch (retryError: any) {
          const status = retryError?.response?.status || retryError?.status;
          const isTimeout = retryError?.code === 'ECONNABORTED' || retryError?.message?.includes('timeout');
          const isRetryable = status === 500 || status === 502 || status === 503 || status === 429 || isTimeout;
          if (isRetryable && retry < MAX_LLM_RETRIES - 1) {
            const waitSec = isTimeout ? 15 : (status === 429 ? Math.min(2 ** retry * 5, 30) : 10);
            const logMsg = isTimeout
              ? `LLM call timed out, retrying in ${waitSec}s (attempt ${retry + 1}/${MAX_LLM_RETRIES})`
              : `LLM call failed with ${status}, retrying in ${waitSec}s (attempt ${retry + 1}/${MAX_LLM_RETRIES})`;
            logger.warn(`[${taskId}] ${logMsg}`);
            yield { type: 'log' as any, data: { level: 'warn', message: logMsg } };
            await new Promise(resolve => setTimeout(resolve, waitSec * 1000));
            continue;
          }
          throw retryError;
        }
      }

      const { message, usage } = result!;

      assistantMessage = AssistantMessageSchema.parse(message);
      turnUsage = usage;
      lastFinishReason = (result as any).finish_reason as string | undefined;
      lastExtra = (result as any).extra as Record<string, any> | undefined;
    } catch (error) {
      // LLM completion or parsing failed, break the loop
      reachedMaxTurns = false;
      yield* handleCompletionError(error, mcpClient);
      break;
    }

    allMessages.push(assistantMessage);
    yield {
      type: 'message',
      data: assistantMessage,
      usage: turnUsage as Record<string, any> | undefined,
      finish_reason: lastFinishReason,
      extra: lastExtra,
      timestamp: new Date().toISOString(),
    };

    const toolCalls = assistantMessage.tool_calls ?? [];
    const turnToolResults: ToolCallOutputMessage[] = [];
    let naturalCompletion = false;

    if (toolCalls.length > 0) {
      for (const rawToolCall of toolCalls) {
        // Check tool call limit before executing
        if (maxToolCalls && totalToolCalls >= maxToolCalls) {
          reachedMaxTurns = false;
          reachedMaxToolCalls = true;
          break;
        }
        totalToolCalls++;
        const toolCall = prunedTools(rawToolCall);
        try {
          const response = await mcpClient.callTool(
            toolCall.function.name,
            JSON.parse(toolCall.function.arguments),
          );
          const toolCallResult = CallToolResponseSchema.parse(response);
          const cappedContent = toolOutputCap
            ? capToolContent(toolCallResult.content, toolOutputCap)
            : toolCallResult.content;
          const toolCallMessage = {
            role: 'tool' as const,
            content: cappedContent,
            tool_call_id: toolCall.id,
          };
          allMessages.push(toolCallMessage);
          yield { type: 'message', data: toolCallMessage };
          turnToolResults.push(toolCallMessage);
        } catch (error) {
          // Tool call failed — feed error back to model so it can recover
          const errorMsg = ((error as any).message || String(error)).split('\n')[0];
          logger.error(`[${taskId}] Tool call failed, feeding error back to model`, {
            toolCall: toolCall.function.name,
            error: errorMsg,
          });
          yield { type: 'log' as any, data: { level: 'error', message: `Tool ${toolCall.function.name} failed: ${errorMsg}` } };
          const errorToolMessage = {
            role: 'tool' as const,
            content: [{ type: 'text' as const, text: `Error: ${errorMsg}` }],
            tool_call_id: toolCall.id,
          };
          allMessages.push(errorToolMessage);
          yield { type: 'message', data: errorToolMessage };
          turnToolResults.push(errorToolMessage);
        }
      }
    } else {
      // Model returned no tool calls — natural completion
      reachedMaxTurns = false;
      naturalCompletion = true;
    }

    // Record this turn as one trajectory step, regardless of which path
    // above it took — a single point so no exit (max-tool-calls, natural
    // completion, or looping again) skips it.
    stepCounter++;
    if (turnUsage) {
      // Anchor and measurement move together. If a turn returns no usage we
      // keep the older pair, so the next projection still accounts for every
      // message appended since the last real measurement instead of silently
      // dropping the turns in between.
      lastPromptTokens = turnUsage.prompt_tokens;
      lastPromptChars = promptChars;
      lastPromptImages = promptImages;
      messageCountAtLastCall = promptMessageCount;
      totalPromptTokens += turnUsage.prompt_tokens;
      totalCompletionTokens += turnUsage.completion_tokens;
      if (turnUsage.cost_usd != null) {
        totalCostUsd = (totalCostUsd ?? 0) + turnUsage.cost_usd;
        costTracked = true;
      }
    }
    trajectorySteps.push({
      step_id: stepCounter,
      timestamp: turnTimestamp,
      message: assistantMessage,
      tool_results: turnToolResults.length > 0 ? turnToolResults : undefined,
      metrics: turnUsage
        ? {
            prompt_tokens: turnUsage.prompt_tokens,
            completion_tokens: turnUsage.completion_tokens,
            total_tokens: turnUsage.total_tokens,
            cost_usd: turnUsage.cost_usd,
          }
        : undefined,
      extra: lastExtra || undefined,
    });

    // Break outer loop if tool call limit reached mid-turn or the model
    // naturally completed (no tool calls returned).
    if (reachedMaxToolCalls || naturalCompletion) break;
  }

  if (reachedMaxToolCalls) {
    logger.warn('Agent loop reached max tool calls', { maxToolCalls, totalToolCalls });
    yield {
      type: 'error',
      data: { reason: 'max_tool_calls_reached', maxToolCalls, totalToolCalls },
    };
  } else if (reachedMaxTurns) {
    logger.warn('Agent loop reached max turns without completing', { maxTurns });
    yield {
      type: 'error',
      data: { reason: 'max_turns_reached', maxTurns },
    };
  }

  // Emitted last, as one more entry in the flat event array. Old consumers
  // (e.g. run_eval.py's `type == "message"` filter) ignore it by construction;
  // new consumers read this one event for the full structured run record.
  yield {
    type: 'trajectory',
    data: {
      schema_version: 'mcp-atlas-trajectory-v1',
      session_id: sessionId,
      task_id: taskId || 'unknown',
      agent: { name: 'litellm', model_name: model },
      final_metrics: {
        total_prompt_tokens: totalPromptTokens,
        total_completion_tokens: totalCompletionTokens,
        total_cost_usd: costTracked ? totalCostUsd : null,
        total_steps: stepCounter,
      },
      steps: trajectorySteps,
    },
  };
}


function _transformToolCalls(toolCalls: ToolDefinition[]): ToolCallDefinition[] {
  return toolCalls.map(toolCall => ({
    type: 'function' as const,
    function: {
      name: toolCall.name,
      description: toolCall.description,
      parameters: {
        ...toolCall.inputSchema,
      },
      strict: false,
    },
  }));
}

// Simple Helper Functions to fix specific tool calls
function prunedTools(rawToolCall: ToolCall) {
  const toolCall = { ...rawToolCall };

  if (toolCall.function.name === 'met-museum_get-museum-object') {
    const args = JSON.parse(toolCall.function.arguments);
    args.returnImage = false; // prevent images from being returned
    toolCall.function.arguments = JSON.stringify(args);
  }
  return toolCall;
}

/**
 * Shared handler for running MCP agent that can be used by different routers
 *
 * @param body - Request body matching RunAgentAPIRequestBodySchema format:
 *   - model: string - The LLM model to use (e.g., "openai/gpt-4o")
 *   - messages: Message[] - Array of conversation message(s). Example: [{"role": "user", "content": "Hello?"}]
 *   - enabledTools: string[] - List of tool names to enable
 *   - image: string - Docker image identifier for the sandbox
 *   - tags: Record<string, string> - Arbitrary tags for the request, for logging/tracing
 *   - max_turns?: number - Maximum number of agent loop iterations (defaults to 256)
 *   - systemPrompt?: string - System prompt for the agent
 *
 * @returns AsyncGenerator<AgentOutput> - Generator that yields either successful messages or errors during agent execution
 */

export async function handleRunMCPAgentEval(body: z.infer<typeof RunAgentAPIRequestBodySchema>) {
  // Use task_id from request body
  const taskId = body.task_id || 'unknown';

  // Extract prompt from user message
  const userMessage = body.messages.find(m => m.role === 'user');
  const promptContent = userMessage?.content;
  const prompt = Array.isArray(promptContent)
    ? promptContent.map((p: any) => p.text || '[media]').join(' ')
    : promptContent || 'No user message found';

  logger.info('=== NEW MCP EVAL REQUEST ===', {
    taskId,
    assignmentId: body.tags?.assignmentId,
    model: body.model,
    strategy: body.strategy || 'default (litellm)',
    llmBaseUrl: body.llm_base_url || config.llmBaseUrl + ' (from .env)',
    prompt: prompt.substring(0, 200) + (prompt.length > 200 ? '...' : ''),
    enabledToolsCount: body.enabledTools.length,
    enabledTools: body.enabledTools,
    messageCount: body.messages.length,
    tags: body.tags,
  });
  // Full conversation (can be large / contain sensitive content) goes to the
  // file-only verbose log, not INFO — keeps server logs lean.
  logger.verbose('=== NEW MCP EVAL REQUEST — full messages ===', { messages: body.messages });

  let mcpClient;
  if (body.image) {
    mcpClient = await createMCPClient({
      type: 'sandbox',
      image: body.image,
      tags: body.tags ?? {},
      enabledTools: body.enabledTools,
    });
  }

  if (!mcpClient) {
    throw new Error('Failed to create MCP client');
  }

  return runMcpAgent({
    mcpClient,
    model: body.model,
    messages: body.messages,
    maxTurns: body.max_turns,
    strategy: body.strategy,
    llmBaseUrl: body.llm_base_url,
    extraLlmParams: body.extra_llm_params,
    taskId,
    contextWindowManagement: body.context_window_management,
    contextWindowTokens: body.context_window_tokens,
    condenserSummarize: body.condenser_summarize,
    condenserModel: body.condenser_model,
    condenserTokenFraction: body.condenser_token_fraction,
    condenserKeepFirst: body.condenser_keep_first,
    toolOutputCap: body.tool_output_cap,
    maxToolCalls: body.max_tool_calls,
  });
}

/**
 * Handler for directly calling a tool via MCP sandbox client
 *
 * @param body - Request body matching CallToolAPIRequestBodySchema format:
 *   - image: string - Docker image identifier for the sandbox
 *   - tags: Record<string, string> - Arbitrary tags for the request, for logging/tracing
 *   - enabledTools: string[] - List of tool names to enable
 *   - toolName: string - Name of the tool to call
 *   - toolArgs: Record<string, any> - Arguments to pass to the tool
 *
 * @returns Promise<ToolCallOutput> - The result of the tool execution
 */
export async function handleCallMCPTool(body: z.infer<typeof CallToolAPIRequestBodySchema>) {
  const mcpClient = await createMCPClient({
    type: 'sandbox',
    image: body.image,
    tags: body.tags ?? {},
  });

  if (!mcpClient) {
    throw new Error('Failed to create MCP client');
  }

  return await mcpClient.callTool(body.toolName, body.toolArgs);
}
