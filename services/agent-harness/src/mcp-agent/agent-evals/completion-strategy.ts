import { type ToolCallDefinition, type Message } from '../types';
import { LiteLLMAgentCompletionStrategy } from './strategies/litellm-strategy';

// Base interfaces that strategies can extend or redefine
export interface BaseCompletionRequest {
  model: string;
  messages: Message[];
  tools: ToolCallDefinition[];
  extraLlmParams?: Record<string, any>;
}

export interface BaseCompletionResult {
  message: Message;
  // Optional — populated when the endpoint's response includes usage/cost.
  // Absent (not zeroed) when the provider doesn't report it, so callers can
  // tell "no data" apart from "zero tokens".
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens?: number;
    cost_usd?: number | null;
  };
}

export interface AgentCompletionStrategy<
  TRequest = BaseCompletionRequest,
  TResult = BaseCompletionResult,
> {
  createCompletion(request: TRequest): Promise<TResult>;
}

/**
 * Factory function for the agent completion strategy.
 *
 * Only LiteLLM is shipped here — it supports any model that's reachable via
 * a LiteLLM proxy (OpenAI, Anthropic, Gemini, self-hosted, etc.). To add a
 * new provider, implement AgentCompletionStrategy in a new file under
 * strategies/ and dispatch from here.
 */
export function getAgentCompletionStrategy(
  _model: string,
  _strategy?: string,
  _llmBaseUrl?: string,
): AgentCompletionStrategy<any, BaseCompletionResult> {
  return new LiteLLMAgentCompletionStrategy();
}
