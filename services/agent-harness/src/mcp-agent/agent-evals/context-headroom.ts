import type { Message } from '../types';

/**
 * Context-window headroom management.
 *
 * Compaction is driven by the model's *actual* token budget, not by a fixed
 * turn count: we only shrink the conversation once the projected next prompt
 * would cross `condenserTokenFraction * contextWindowTokens` — by default the
 * full 1M window. Below that line the message array is passed through by
 * reference, untouched.
 *
 * The turn-count trigger is kept only as a backstop for the case where no
 * token budget can be resolved (window or fraction unset / non-positive), so
 * headroom protection is never silently lost.
 *
 * This module is deliberately free of I/O and of `../../config` imports so it
 * stays pure and can be exercised by scripts/check-headroom.ts without any
 * environment set up.
 */

/**
 * Context-window strategy requested by the caller.
 *   'compact' / 'headroom' — manage headroom: compaction is triggered by the
 *     projected token size of the next prompt, with the turn-count path kept
 *     only as a backstop. 'compact' is the historical spelling and stays
 *     accepted so existing callers are unaffected.
 *   'off' — an explicit, real off switch: identical to omitting the field.
 * Omitting the field leaves the conversation uncompacted, as before.
 */
export type ContextWindowManagement = 'compact' | 'headroom' | 'off';

/**
 * True when the caller asked for headroom management and did not turn it off.
 * The off switch is load-bearing: 'off' and an absent value both mean the
 * message list is sent through untouched.
 */
export function isHeadroomEnabled(mode?: ContextWindowManagement): boolean {
  return mode === 'compact' || mode === 'headroom';
}

/** Default context window, in tokens, when the caller does not specify one. */
export const DEFAULT_CONTEXT_WINDOW_TOKENS = 1_000_000;
/**
 * Fraction of the window at which compaction fires. 1.0 → the trigger sits at
 * the window itself, so a 1M-token window compacts once the projected prompt
 * passes 1_000_000. Lower it to reserve margin for the completion and for
 * projection error (0.8 → 800_000).
 */
export const DEFAULT_CONDENSER_TOKEN_FRACTION = 1.0;
/** Leading messages that are never truncated (system prompt + task statement). */
export const DEFAULT_CONDENSER_KEEP_FIRST = 2;

/** Trailing turns whose tool results always stay at full fidelity. */
export const COMPACT_KEEP_FULL_TURNS = 2;
/** Per-tool-result char cap used by the legacy turn-triggered backstop. */
export const COMPACT_TRUNCATE_THRESHOLD = 1500;

/**
 * Escalating per-tool-result char caps. Each rung is applied to the *original*
 * messages (never to an already-truncated pass) so truncation markers never
 * nest, and we stop at the first rung that gets the projection under budget.
 */
export const COMPACT_TRUNCATE_LADDER = [1500, 600, 200];

/**
 * Chars per token used when no measured `prompt_tokens` is available.
 *
 * BPE tokenizers average ~4 chars/token on English prose, but what fills this
 * conversation is JSON-serialized tool output — braces, quotes, ids, paths,
 * code — which tokenizes denser, closer to ~3. We use 3.5 as the conservative
 * middle: it over-counts prose, so the fallback errs toward compacting a little
 * early rather than a little late. No tokenizer dependency is added; this is
 * only a fallback, the measured prompt_tokens from the previous turn is used
 * whenever it exists.
 */
export const CHARS_PER_TOKEN = 3.5;

/**
 * Flat token cost charged for one image content item.
 *
 * Vision models bill images by tile count, not by the length of the base64
 * payload, so counting those bytes as text is wrong by two orders of magnitude
 * — a 750 KB scan is ~1.6k tokens, not ~215k. Images are therefore counted
 * per-item and their payload bytes are excluded from the char total. The exact
 * figure varies by model and resolution; this is a deliberate over-estimate of
 * a typical full-page scan, so the error stays on the safe side.
 */
export const IMAGE_TOKENS_ESTIMATE = 1600;

/** True for a content item the model bills as an image rather than as text. */
function isImageItem(item: any): boolean {
  return item?.type === 'image' || item?.type === 'image_url' || !!item?.image_url;
}

export interface PromptSize {
  /** Serialized size of everything except image payloads. */
  textChars: number;
  /** Number of image content items. */
  imageCount: number;
}

/**
 * Measure one message, keeping image payloads out of the char count and
 * tallying them separately.
 */
function sizeOfMessage(msg: Message): PromptSize {
  const m = msg as any;
  if (!Array.isArray(m.content)) return { textChars: JSON.stringify(m)?.length ?? 0, imageCount: 0 };
  let imageCount = 0;
  const scrubbed = {
    ...m,
    content: m.content.map((c: any) => {
      if (!isImageItem(c)) return c;
      imageCount++;
      return { type: 'image' }; // payload excluded; billed per item instead
    }),
  };
  return { textChars: JSON.stringify(scrubbed)?.length ?? 0, imageCount };
}

/** Measure a whole message list — text chars and image count, kept apart. */
export function measurePrompt(messages: Message[]): PromptSize {
  let textChars = 0;
  let imageCount = 0;
  for (const msg of messages) {
    const size = sizeOfMessage(msg);
    textChars += size.textChars;
    imageCount += size.imageCount;
  }
  return { textChars, imageCount };
}

/**
 * Sanity bounds for a calibrated ratio. Anything outside this is a sign the
 * provider reported something we should not extrapolate from (a cached prompt,
 * a stubbed count, an image-heavy turn), so we keep the default instead.
 */
const MIN_CHARS_PER_TOKEN = 1.5;
const MAX_CHARS_PER_TOKEN = 12;

/**
 * Recover the provider's actual chars-per-token from one measurement: the
 * serialized size of the prompt we sent and the prompt_tokens we were billed
 * for it. Self-calibrating this beats the CHARS_PER_TOKEN guess outright —
 * the constant is only ever a first-turn stand-in — because it is measured on
 * this model, with this conversation's actual content.
 *
 * Returns the default when there is nothing trustworthy to calibrate from.
 */
export function calibrateCharsPerToken(
  promptChars?: number,
  promptTokens?: number,
  imageCount = 0,
): number {
  if (!promptChars || !promptTokens) return CHARS_PER_TOKEN;
  if (!Number.isFinite(promptChars) || !Number.isFinite(promptTokens)) return CHARS_PER_TOKEN;
  if (promptChars <= 0 || promptTokens <= 0) return CHARS_PER_TOKEN;
  // Bill the images out first, so what is left is a text-only ratio. Without
  // this a page scan drags the measured ratio into the hundreds and the guard
  // below rejects every calibration on a multimodal run.
  const textTokens = promptTokens - Math.max(0, imageCount) * IMAGE_TOKENS_ESTIMATE;
  if (textTokens <= 0) return CHARS_PER_TOKEN;
  const ratio = promptChars / textTokens;
  if (ratio < MIN_CHARS_PER_TOKEN || ratio > MAX_CHARS_PER_TOKEN) return CHARS_PER_TOKEN;
  return ratio;
}

/**
 * Project a post-compaction prompt size: the size before, less the chars we
 * removed converted at CHARS_PER_TOKEN. Anchoring on the measured prompt and
 * applying a delta keeps the projection honest even when the "before" number
 * came from the provider rather than from our own estimate.
 */
export function projectTokensAfter(
  promptTokensBefore: number,
  savedChars: number,
  charsPerToken: number = CHARS_PER_TOKEN,
): number {
  return Math.max(0, promptTokensBefore - Math.floor(savedChars / charsPerToken));
}

/**
 * Serialized size of a message list in characters, excluding image payloads —
 * those are counted as {@link IMAGE_TOKENS_ESTIMATE} each instead.
 */
export function messageChars(messages: Message[]): number {
  return measurePrompt(messages).textChars;
}

/** Arithmetic token estimate for a message list — see {@link CHARS_PER_TOKEN}. */
export function estimateMessageTokens(
  messages: Message[],
  charsPerToken: number = CHARS_PER_TOKEN,
): number {
  const { textChars, imageCount } = measurePrompt(messages);
  return Math.ceil(textChars / charsPerToken) + imageCount * IMAGE_TOKENS_ESTIMATE;
}

/**
 * Resolve the compaction threshold from a context window and a fraction.
 * Returns null when no budget can be determined — callers then fall back to
 * the turn-count backstop rather than running with no headroom protection.
 */
export function resolveThresholdTokens(
  contextWindowTokens?: number,
  condenserTokenFraction?: number,
): number | null {
  if (!contextWindowTokens || !Number.isFinite(contextWindowTokens) || contextWindowTokens <= 0) return null;
  if (!condenserTokenFraction || !Number.isFinite(condenserTokenFraction) || condenserTokenFraction <= 0) return null;
  const threshold = Math.floor(contextWindowTokens * condenserTokenFraction);
  return threshold > 0 ? threshold : null;
}

export interface HeadroomDecision {
  /** True when the projected next prompt crosses the threshold. */
  shouldCompact: boolean;
  /** Projected prompt size for the call we are about to make, in tokens. */
  promptTokensBefore: number;
  /** Compaction trigger point, or null when no token budget resolved. */
  thresholdTokens: number | null;
  /** The window the threshold came from, or null when unresolved. */
  contextWindowTokens: number | null;
  /** Whether the projection is anchored on measured usage or a char estimate. */
  usageSource: 'usage' | 'estimate';
  /** Which trigger is in force for this turn. */
  trigger: 'token-budget' | 'turn-backstop';
  /** The chars-per-token ratio this decision was computed with. */
  charsPerToken: number;
}

export interface HeadroomInput {
  messages: Message[];
  /** `prompt_tokens` measured on the previous LLM call, if any. */
  lastPromptTokens?: number;
  /** How many trailing messages were appended after that measured call. */
  messagesSinceLastCall?: number;
  contextWindowTokens?: number;
  condenserTokenFraction?: number;
  /** Calibrated chars-per-token; defaults to the CHARS_PER_TOKEN constant. */
  charsPerToken?: number;
}

/**
 * Decide whether the next LLM call needs compaction.
 *
 * The projection is the last measured prompt plus an estimate of everything
 * appended since (the assistant message and its tool results) — i.e. the real
 * size of the prompt we are about to send, not the size of the one we sent
 * last turn. With no measurement yet (first turn, or a strategy that returns
 * no usage) the whole conversation is estimated arithmetically instead.
 */
export function evaluateHeadroom({
  messages,
  lastPromptTokens,
  messagesSinceLastCall,
  contextWindowTokens,
  condenserTokenFraction,
  charsPerToken = CHARS_PER_TOKEN,
}: HeadroomInput): HeadroomDecision {
  const thresholdTokens = resolveThresholdTokens(contextWindowTokens, condenserTokenFraction);

  const measured =
    typeof lastPromptTokens === 'number' && Number.isFinite(lastPromptTokens) && lastPromptTokens > 0;
  const usageSource: 'usage' | 'estimate' = measured ? 'usage' : 'estimate';

  let promptTokensBefore: number;
  if (measured) {
    const appended = messagesSinceLastCall && messagesSinceLastCall > 0
      ? messages.slice(messages.length - messagesSinceLastCall)
      : [];
    promptTokensBefore = lastPromptTokens! + estimateMessageTokens(appended, charsPerToken);
  } else {
    promptTokensBefore = estimateMessageTokens(messages, charsPerToken);
  }

  if (thresholdTokens === null) {
    // No token budget — the caller falls back to the turn-count backstop.
    return {
      shouldCompact: false,
      promptTokensBefore,
      thresholdTokens: null,
      contextWindowTokens: null,
      usageSource,
      trigger: 'turn-backstop',
      charsPerToken,
    };
  }

  return {
    shouldCompact: promptTokensBefore > thresholdTokens,
    promptTokensBefore,
    thresholdTokens,
    contextWindowTokens: contextWindowTokens!,
    usageSource,
    trigger: 'token-budget',
    charsPerToken,
  };
}

/**
 * Markers we stamp onto reduced tool results. They double as idempotence
 * guards: a result we already reduced is re-reduced only when a tighter cap
 * would genuinely make it smaller, and the tighter slice cuts the old marker
 * off rather than nesting a second one inside it.
 */
const TRUNCATION_MARKER_PREFIX = '\n\n[Tool call output too large, truncated to ';
const DROP_MARKER_PREFIX = '[Tool call output dropped';

/** Length of a tool result ignoring any marker we previously appended. */
function bodyLength(text: string): number {
  if (text.startsWith(DROP_MARKER_PREFIX)) return 0;
  const idx = text.lastIndexOf(TRUNCATION_MARKER_PREFIX);
  return idx >= 0 && text.endsWith(']') ? idx : text.length;
}

/** Flatten a tool message's content to plain text. */
function toolText(m: any): string {
  return Array.isArray(m.content)
    ? m.content.map((c: any) => c.text || '').join('')
    : String(m.content ?? '');
}

/**
 * Rebuild a tool message with new text, preserving its content shape *and*
 * every non-text item it carried.
 *
 * Reduction only ever rewrites text. An image is the evidence itself on a
 * scanned-document task and cannot be recovered from a summary of its byte
 * count, so it survives truncation and dropping alike — and it costs a flat
 * IMAGE_TOKENS_ESTIMATE regardless, meaning discarding it would buy almost
 * nothing anyway.
 */
function withText(m: any, text: string): Message {
  if (!Array.isArray(m.content)) return { ...m, content: text } as Message;
  // Everything that is not text is preserved, not just images: an unknown
  // content type is exactly the thing we must not quietly delete.
  const preserved = m.content.filter((c: any) => c?.type !== 'text');
  return { ...m, content: [{ type: 'text', text }, ...preserved] } as Message;
}

/**
 * Index of the first message belonging to the last COMPACT_KEEP_FULL_TURNS
 * turns. Everything before it is eligible for truncation; -1 means the
 * conversation is not yet longer than the turns we always keep whole.
 */
export function truncationBoundary(messages: Message[]): number {
  const turnStarts: number[] = [];
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i] as any;
    if (msg.role === 'assistant' && msg.tool_calls?.length > 0) turnStarts.push(i);
  }
  const turnsToTruncate = turnStarts.length - COMPACT_KEEP_FULL_TURNS;
  if (turnsToTruncate <= 0) return -1;
  return turnStarts[turnsToTruncate];
}

/**
 * Truncate every eligible tool result down to `cap` chars. Eligible means:
 * index >= keepFirst (system prompt + task statement are untouchable) and
 * index < boundary (the last COMPACT_KEEP_FULL_TURNS stay whole).
 */
function applyCap(
  messages: Message[],
  cap: number,
  boundary: number,
  keepFirst: number,
): { messages: Message[]; savedChars: number; truncatedCount: number } {
  let savedChars = 0;
  let truncatedCount = 0;
  const out = messages.map((msg, idx) => {
    if (idx < keepFirst || idx >= boundary) return msg;
    const m = msg as any;
    if (m.role !== 'tool') return msg;
    const contentStr = toolText(m);
    if (bodyLength(contentStr) <= cap) return msg;
    const truncatedText =
      contentStr.slice(0, cap) +
      `${TRUNCATION_MARKER_PREFIX}${cap} chars. Original was ${contentStr.length} chars.]`;
    savedChars += contentStr.length - truncatedText.length;
    truncatedCount++;
    return withText(m, truncatedText);
  });
  return { messages: savedChars > 0 ? out : messages, savedChars, truncatedCount };
}

export interface CompactionOutcome {
  messages: Message[];
  /** False when nothing could be shrunk — `messages` is then the input by reference. */
  changed: boolean;
  savedChars: number;
  /** Projected prompt size after compaction, in tokens. */
  estimatedTokensAfter: number;
  /** Whether the projection now fits under the threshold. */
  underThreshold: boolean;
  /** Ladder rung that ended up applied, or null if nothing was truncated. */
  capApplied: number | null;
  truncatedCount: number;
  droppedCount: number;
  /** tool_call_ids whose output was discarded entirely — logged, never silent. */
  droppedToolCallIds: string[];
}

export interface CompactToBudgetInput {
  /** Projected prompt size before compaction (from evaluateHeadroom). */
  promptTokensBefore: number;
  thresholdTokens: number;
  keepFirst?: number;
  /** Calibrated chars-per-token; defaults to the CHARS_PER_TOKEN constant. */
  charsPerToken?: number;
}

/**
 * Shrink the conversation until the projection fits under `thresholdTokens`,
 * escalating as needed: cap eligible tool results at 1500 chars, then 600,
 * then 200, then discard the oldest truncated tool results outright.
 *
 * Discarded results keep their message and `tool_call_id` — dropping the
 * message itself would orphan the assistant's tool_call and be rejected by the
 * chat-completions API — but their text is replaced by a marker recording how
 * much was thrown away.
 *
 * The post-compaction projection is `promptTokensBefore` minus the chars saved
 * converted at CHARS_PER_TOKEN, so it stays anchored on the measured prompt
 * when there is one rather than swapping to a pure estimate mid-decision.
 */
export function compactToBudget(
  messages: Message[],
  {
    promptTokensBefore,
    thresholdTokens,
    keepFirst: rawKeepFirst = DEFAULT_CONDENSER_KEEP_FIRST,
    charsPerToken = CHARS_PER_TOKEN,
  }: CompactToBudgetInput,
): CompactionOutcome {
  const keepFirst = Math.max(0, Math.floor(rawKeepFirst));
  const project = (savedChars: number) => projectTokensAfter(promptTokensBefore, savedChars, charsPerToken);
  const unchanged: CompactionOutcome = {
    messages,
    changed: false,
    savedChars: 0,
    estimatedTokensAfter: promptTokensBefore,
    underThreshold: promptTokensBefore <= thresholdTokens,
    capApplied: null,
    truncatedCount: 0,
    droppedCount: 0,
    droppedToolCallIds: [],
  };

  // Already inside the budget — hand the caller its own array back, untouched.
  if (promptTokensBefore <= thresholdTokens) return unchanged;

  const boundary = truncationBoundary(messages);
  if (boundary < 0 || boundary <= keepFirst) return unchanged;

  let best = messages;
  let savedChars = 0;
  let capApplied: number | null = null;
  let truncatedCount = 0;

  for (const cap of COMPACT_TRUNCATE_LADDER) {
    // Each rung re-truncates from the original, so markers never nest.
    const pass = applyCap(messages, cap, boundary, keepFirst);
    best = pass.messages;
    savedChars = pass.savedChars;
    truncatedCount = pass.truncatedCount;
    capApplied = pass.savedChars > 0 ? cap : capApplied;
    if (project(savedChars) <= thresholdTokens) break;
  }

  const droppedToolCallIds: string[] = [];
  let droppedCount = 0;
  if (project(savedChars) > thresholdTokens) {
    // Still over budget after the tightest cap — discard oldest-first.
    const dropped = [...best];
    for (let idx = keepFirst; idx < boundary && project(savedChars) > thresholdTokens; idx++) {
      const m = dropped[idx] as any;
      if (m?.role !== 'tool') continue;
      const contentStr = toolText(m);
      if (contentStr.length === 0 || contentStr.startsWith(DROP_MARKER_PREFIX)) continue;
      const marker = `${DROP_MARKER_PREFIX} to fit the context window. ${contentStr.length} chars discarded.]`;
      // Nothing to reclaim: a short caption on an image result costs less than
      // the marker that would replace it, so dropping it is pure loss.
      if (marker.length >= contentStr.length) continue;
      savedChars += contentStr.length - marker.length;
      dropped[idx] = withText(m, marker);
      droppedCount++;
      // A result without a tool_call_id still counts as dropped — the count is
      // what must never disagree with the array we return.
      if (m.tool_call_id) droppedToolCallIds.push(m.tool_call_id);
    }
    if (droppedCount > 0) best = dropped;
  }

  if (savedChars <= 0) return unchanged;

  return {
    messages: best,
    changed: true,
    savedChars,
    estimatedTokensAfter: project(savedChars),
    underThreshold: project(savedChars) <= thresholdTokens,
    capApplied,
    truncatedCount,
    droppedCount,
    droppedToolCallIds,
  };
}

export interface CompactionPlanInput {
  /** Turn index (0-based), only consulted by the turn-count backstop. */
  turnIndex: number;
  /** `prompt_tokens` from the last call that reported usage, if any. */
  lastPromptTokens?: number;
  /** Message count of that measured prompt, so growth since can be projected. */
  messageCountAtLastCall?: number;
  /** Text size of that measured prompt (image payloads excluded), for calibration. */
  lastPromptChars?: number;
  /** Image items in that measured prompt, billed out before calibrating. */
  lastPromptImages?: number;
  contextWindowTokens?: number;
  condenserTokenFraction?: number;
  keepFirst?: number;
  /**
   * Return the decision without running the truncating reduction. Used when a
   * summarizing pass will be tried first: computing a reduction only to throw
   * it away costs a full pass over the conversation.
   */
  skipReduction?: boolean;
}

export interface CompactionPlan {
  /** What to send. Identical (by reference) to the input when nothing changed. */
  messagesToSend: Message[];
  decision: HeadroomDecision;
  /** Present only on the token-budget path; null when the backstop ran. */
  outcome: CompactionOutcome | null;
}

/**
 * The whole per-turn headroom decision in one pure call: measure, choose a
 * trigger, and produce the message list to send.
 *
 * This is the state machine the agent loop runs before every LLM call. It
 * lives here rather than inline in the loop so it can be exercised directly —
 * the loop keeps only what is genuinely its own: logging the result, emitting
 * the compaction event, and persisting the reduction.
 */
export function planCompaction(messages: Message[], input: CompactionPlanInput): CompactionPlan {
  // Calibrate on the provider's own accounting where we have it: the chars we
  // sent last time against the prompt_tokens we were billed for them.
  const charsPerToken = calibrateCharsPerToken(
    input.lastPromptChars,
    input.lastPromptTokens,
    input.lastPromptImages,
  );
  const decision = evaluateHeadroom({
    messages,
    lastPromptTokens: input.lastPromptTokens,
    messagesSinceLastCall: messages.length - (input.messageCountAtLastCall ?? 0),
    contextWindowTokens: input.contextWindowTokens,
    condenserTokenFraction: input.condenserTokenFraction,
    charsPerToken,
  });

  if (decision.trigger === 'turn-backstop') {
    // No token budget could be resolved — fall back to the turn-count trigger
    // so headroom protection is never silently lost.
    return {
      messagesToSend: compactMessages(messages, input.turnIndex, input.keepFirst),
      decision,
      outcome: null,
    };
  }

  if (!decision.shouldCompact || input.skipReduction) {
    return { messagesToSend: messages, decision, outcome: null };
  }

  const outcome = compactToBudget(messages, {
    promptTokensBefore: decision.promptTokensBefore,
    thresholdTokens: decision.thresholdTokens!,
    keepFirst: input.keepFirst,
    charsPerToken,
  });
  return { messagesToSend: outcome.changed ? outcome.messages : messages, decision, outcome };
}

// ---------------------------------------------------------------------------
// Summarizing condenser
// ---------------------------------------------------------------------------

/**
 * Instruction given to the summarizer. Mirrors what goku's
 * LLMSummarizingCondenser is for: the older turns stop being raw transcript
 * and become a carried-forward brief, so the agent keeps the *findings* after
 * the bytes are gone. Written to preserve exactly the things a truncation
 * would destroy — values read, decisions made, and what is still outstanding.
 */
export const SUMMARY_INSTRUCTION = [
  'You are condensing the earlier part of an agent transcript so the agent can keep working',
  'after the raw text is discarded. This summary REPLACES those turns — anything you leave out',
  'is lost permanently.',
  '',
  'Write a dense factual brief covering:',
  '1. FINDINGS — every concrete value, figure, id, path, name or quote the agent established.',
  '   Reproduce them exactly. Never round, never say "several" where you can give the number.',
  '2. ACTIONS — what the agent did, which tools it called, and what changed as a result.',
  '3. DECISIONS — conclusions reached and the reason for each, including things ruled out.',
  '4. OUTSTANDING — what remains unfinished, unverified, or blocked.',
  '',
  'Be terse and factual. No preamble, no restating the task, no commentary on the summary itself.',
].join('\n');

export interface SummaryRequest {
  /** First index of the span being summarized (inclusive). */
  spanStart: number;
  /** End of the span (exclusive) — the last kept turns begin here. */
  spanEnd: number;
  /** Messages to send to the summarizer. */
  messages: Message[];
  /** Tool-result messages inside the span, which the summary will replace. */
  reducibleToolIndices: number[];
}

/**
 * Build the summarizer call for a conversation, or null when there is nothing
 * old enough to condense (same eligibility rule the truncating path uses:
 * after `keepFirst`, before the last COMPACT_KEEP_FULL_TURNS turns).
 */
export function buildSummaryRequest(
  messages: Message[],
  rawKeepFirst: number = DEFAULT_CONDENSER_KEEP_FIRST,
): SummaryRequest | null {
  const keepFirst = Math.max(0, Math.floor(rawKeepFirst));
  const boundary = truncationBoundary(messages);
  if (boundary < 0 || boundary <= keepFirst) return null;

  const reducibleToolIndices: number[] = [];
  for (let i = keepFirst; i < boundary; i++) {
    const m = messages[i] as any;
    if (m?.role === 'tool' && toolText(m).length > 0 && !toolText(m).startsWith(DROP_MARKER_PREFIX)) {
      reducibleToolIndices.push(i);
    }
  }
  if (reducibleToolIndices.length === 0) return null;

  // Feed the summarizer a text-only rendering of the span. Images are not sent
  // — they stay in the conversation untouched, so re-describing them would both
  // cost vision tokens and risk replacing evidence with a paraphrase of it.
  const transcript = messages.slice(keepFirst, boundary).map((msg) => {
    const m = msg as any;
    if (m.role === 'assistant') {
      const calls = (m.tool_calls ?? []).map((t: any) => `${t.function?.name}(${t.function?.arguments})`).join(', ');
      return `ASSISTANT: ${m.content ?? ''}${calls ? `
  calls: ${calls}` : ''}`;
    }
    if (m.role === 'tool') {
      const imgs = Array.isArray(m.content) ? m.content.filter(isImageItem).length : 0;
      return `TOOL RESULT${imgs ? ` (+${imgs} image(s), retained separately)` : ''}: ${toolText(m)}`;
    }
    return `${String(m.role).toUpperCase()}: ${typeof m.content === 'string' ? m.content : JSON.stringify(m.content)}`;
  }).join('\n\n');

  return {
    spanStart: keepFirst,
    spanEnd: boundary,
    reducibleToolIndices,
    messages: [
      { role: 'system', content: SUMMARY_INSTRUCTION } as unknown as Message,
      { role: 'user', content: transcript } as unknown as Message,
    ],
  };
}

/** Marker identifying a tool result whose content the summary now carries. */
const SUMMARIZED_MARKER_PREFIX = '[Summarized';

/**
 * Fold a summary back into the conversation.
 *
 * The message list keeps its shape: every tool result keeps its message and its
 * `tool_call_id`, because deleting one would orphan the assistant tool_call it
 * answers and the chat-completions API would reject the request. The summary
 * text lands in the first reducible result; the rest point at it. Non-text
 * content — images above all — is carried through untouched.
 */
export function applySummary(
  messages: Message[],
  summary: string,
  request: SummaryRequest,
): Message[] {
  const [first, ...rest] = request.reducibleToolIndices;
  const out = [...messages];
  out[first] = withText(
    messages[first] as any,
    `${SUMMARIZED_MARKER_PREFIX} — the ${request.reducibleToolIndices.length} earlier tool results in this ` +
    `conversation were condensed to the brief below. The raw text is no longer available.]\n\n${summary}`,
  );
  for (const idx of rest) {
    out[idx] = withText(messages[idx] as any, `${SUMMARIZED_MARKER_PREFIX} — folded into the consolidated brief above.]`);
  }
  return out;
}

/**
 * Legacy turn-triggered compaction — the backstop used only when no token
 * budget can be resolved. Truncates every tool result older than the last
 * COMPACT_KEEP_FULL_TURNS turns to COMPACT_TRUNCATE_THRESHOLD chars, from
 * turn COMPACT_KEEP_FULL_TURNS onward, leaving the first `keepFirst` messages
 * alone.
 */
export function compactMessages(
  messages: Message[],
  currentTurn: number,
  rawKeepFirst: number = DEFAULT_CONDENSER_KEEP_FIRST,
): Message[] {
  if (currentTurn <= COMPACT_KEEP_FULL_TURNS) return messages;
  const keepFirst = Math.max(0, Math.floor(rawKeepFirst));
  const boundary = truncationBoundary(messages);
  if (boundary < 0 || boundary <= keepFirst) return messages;
  return applyCap(messages, COMPACT_TRUNCATE_THRESHOLD, boundary, keepFirst).messages;
}
