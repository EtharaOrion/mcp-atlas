/**
 * Behavioural checks for context-window headroom management.
 *
 * There is no test runner in this service and adding one is out of scope, so
 * this is a plain tsx-runnable script over the pure helpers in
 * src/mcp-agent/agent-evals/context-headroom.ts:
 *
 *   npx tsx scripts/check-headroom.ts        (or: npm run check:headroom)
 *
 * Exits non-zero on the first failed assertion.
 */
import type { Message } from '../src/mcp-agent/types';
import {
  CHARS_PER_TOKEN,
  calibrateCharsPerToken,
  DEFAULT_CONDENSER_KEEP_FIRST,
  DEFAULT_CONDENSER_TOKEN_FRACTION,
  DEFAULT_CONTEXT_WINDOW_TOKENS,
  compactMessages,
  compactToBudget,
  estimateMessageTokens,
  evaluateHeadroom,
  applySummary,
  buildSummaryRequest,
  IMAGE_TOKENS_ESTIMATE,
  isHeadroomEnabled,
  measurePrompt,
  messageChars,
  planCompaction,
  resolveThresholdTokens,
} from '../src/mcp-agent/agent-evals/context-headroom';

let failures = 0;
let checks = 0;

function check(name: string, condition: boolean, detail?: unknown): void {
  checks++;
  if (condition) {
    console.log(`  ok   ${name}`);
  } else {
    failures++;
    console.error(`  FAIL ${name}${detail === undefined ? '' : ` — ${JSON.stringify(detail)}`}`);
  }
}

const onceSeen = new Set<string>();
/** Assert a per-iteration invariant, reporting it a single time. */
function checkOnce(name: string, condition: boolean): void {
  if (onceSeen.has(name)) return;
  onceSeen.add(name);
  check(name, condition);
}

function section(title: string): void {
  console.log(`\n${title}`);
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** A conversation of `turns` tool-calling turns, each tool result `size` chars. */
function buildConversation(turns: number, size: number): Message[] {
  const messages: Message[] = [
    { role: 'system', content: 'SYSTEM PROMPT' } as unknown as Message,
    { role: 'user', content: 'TASK STATEMENT' } as unknown as Message,
  ];
  for (let t = 0; t < turns; t++) {
    messages.push({
      role: 'assistant',
      content: null,
      tool_calls: [
        { id: `call_${t}`, type: 'function', function: { name: 'search', arguments: '{}' } },
      ],
    } as unknown as Message);
    messages.push({
      role: 'tool',
      tool_call_id: `call_${t}`,
      content: [{ type: 'text', text: `T${t}:` + 'x'.repeat(size) }],
    } as unknown as Message);
  }
  return messages;
}

function toolTextAt(messages: Message[], idx: number): string {
  const m = messages[idx] as any;
  return Array.isArray(m.content) ? m.content.map((c: any) => c.text || '').join('') : String(m.content ?? '');
}

// ---------------------------------------------------------------------------
// (a) Below threshold → messages pass through by reference
// ---------------------------------------------------------------------------

section('(a) below threshold → untouched pass-through');
{
  const messages = buildConversation(10, 20_000);
  const decision = evaluateHeadroom({
    messages,
    lastPromptTokens: 1000,
    messagesSinceLastCall: 2,
    contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS,
    condenserTokenFraction: DEFAULT_CONDENSER_TOKEN_FRACTION,
  });

  check(
    'threshold is fraction × window',
    decision.thresholdTokens === Math.floor(DEFAULT_CONTEXT_WINDOW_TOKENS * DEFAULT_CONDENSER_TOKEN_FRACTION),
    decision.thresholdTokens,
  );
  check('the default trigger is the full 1M window', decision.thresholdTokens === 1_000_000, decision.thresholdTokens);
  check('a lower fraction reserves margin', resolveThresholdTokens(1_000_000, 0.8) === 800_000);
  check('trigger is the token budget', decision.trigger === 'token-budget', decision.trigger);
  check('usage from the measured prompt', decision.usageSource === 'usage', decision.usageSource);
  check('does not fire below the threshold', decision.shouldCompact === false, decision);

  // A conversation this size would have been compacted every turn by the old
  // turn-count trigger; under the token budget it is left alone.
  const legacy = compactMessages(messages, 9, DEFAULT_CONDENSER_KEEP_FIRST);
  check('legacy turn trigger would have fired here', legacy !== messages);

  // And the loop's contract: when it does not fire, the array is the same ref.
  const outcome = compactToBudget(messages, {
    promptTokensBefore: decision.promptTokensBefore,
    thresholdTokens: decision.thresholdTokens!,
    keepFirst: DEFAULT_CONDENSER_KEEP_FIRST,
  });
  check('compactToBudget is a no-op under budget', outcome.changed === false && outcome.messages === messages);
  check('no-op reports the input size unchanged', outcome.estimatedTokensAfter === decision.promptTokensBefore);
}

// ---------------------------------------------------------------------------
// (b) Above threshold → older tool results shrink, keepFirst + last 2 turns intact
// ---------------------------------------------------------------------------

section('(b) above threshold → older results shrink, edges preserved');
{
  const messages = buildConversation(8, 40_000);
  const before = messages.map(m => JSON.stringify(m));
  const promptTokensBefore = estimateMessageTokens(messages);
  const thresholdTokens = Math.floor(promptTokensBefore * 0.5);

  const outcome = compactToBudget(messages, {
    promptTokensBefore,
    thresholdTokens,
    keepFirst: DEFAULT_CONDENSER_KEEP_FIRST,
  });

  check('compaction fired', outcome.changed === true);
  check('got under the threshold', outcome.underThreshold === true, {
    after: outcome.estimatedTokensAfter,
    thresholdTokens,
  });
  check('estimate after is smaller than before', outcome.estimatedTokensAfter < promptTokensBefore, {
    before: promptTokensBefore,
    after: outcome.estimatedTokensAfter,
  });

  const out = outcome.messages;
  check('message count is preserved', out.length === messages.length, out.length);
  check('input array not mutated', messages.every((m, i) => JSON.stringify(m) === before[i]));

  // keepFirst: system prompt + task statement byte-identical.
  check(
    'first keepFirst messages untouched',
    out.slice(0, DEFAULT_CONDENSER_KEEP_FIRST).every((m, i) => JSON.stringify(m) === before[i]),
  );

  // Last COMPACT_KEEP_FULL_TURNS turns (4 messages) untouched.
  const tail = out.length - 4;
  check(
    'last 2 turns untouched',
    out.slice(tail).every((m, i) => JSON.stringify(m) === before[tail + i]),
  );

  // Older tool results really did shrink.
  const olderToolIdx = 3; // first turn's tool result
  check('oldest tool result shrank', toolTextAt(out, olderToolIdx).length < 40_000, {
    len: toolTextAt(out, olderToolIdx).length,
  });
  check('shrunken result keeps its tool_call_id', (out[olderToolIdx] as any).tool_call_id === 'call_0');
  check('every tool message still pairs with a tool_call_id', out.every((m: any) => m.role !== 'tool' || !!m.tool_call_id));

  // Escalation: a threshold no cap alone can reach forces outright drops.
  const brutal = compactToBudget(messages, {
    promptTokensBefore,
    thresholdTokens: Math.floor(promptTokensBefore * 0.02),
    keepFirst: DEFAULT_CONDENSER_KEEP_FIRST,
  });
  check('escalates to the tightest cap', brutal.capApplied === 200, brutal.capApplied);
  check('escalates to dropping oldest results', brutal.droppedCount > 0, brutal.droppedCount);
  check('drops are reported, not silent', brutal.droppedToolCallIds.length === brutal.droppedCount, brutal.droppedToolCallIds);
  check('dropped ids are the oldest ones', brutal.droppedToolCallIds[0] === 'call_0', brutal.droppedToolCallIds);
  check('drops still preserve keepFirst', JSON.stringify(brutal.messages[0]) === before[0] && JSON.stringify(brutal.messages[1]) === before[1]);
  check(
    'drops still preserve the last 2 turns',
    brutal.messages.slice(tail).every((m, i) => JSON.stringify(m) === before[tail + i]),
  );
  check('message count preserved after drops', brutal.messages.length === messages.length);

  // Re-running over already-reduced messages must not nest markers.
  const again = compactToBudget(outcome.messages, {
    promptTokensBefore: outcome.estimatedTokensAfter,
    thresholdTokens,
    keepFirst: DEFAULT_CONDENSER_KEEP_FIRST,
  });
  const marker = 'truncated to';
  const nested = toolTextAt(again.messages, olderToolIdx).split(marker).length - 1;
  check('reduction markers do not nest', nested <= 1, { nested });
}

// ---------------------------------------------------------------------------
// (c) Missing usage → estimate fallback, no throw
// ---------------------------------------------------------------------------

section('(c) missing usage → estimate fallback');
{
  const messages = buildConversation(6, 30_000);

  const first = evaluateHeadroom({
    messages,
    contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS,
    condenserTokenFraction: DEFAULT_CONDENSER_TOKEN_FRACTION,
  });
  check('falls back to the char estimate', first.usageSource === 'estimate', first.usageSource);
  check('estimate matches CHARS_PER_TOKEN arithmetic', first.promptTokensBefore === estimateMessageTokens(messages));
  check('estimate is a positive finite number', Number.isFinite(first.promptTokensBefore) && first.promptTokensBefore > 0);
  check('CHARS_PER_TOKEN is the documented 3.5', CHARS_PER_TOKEN === 3.5);

  for (const bad of [undefined, 0, -1, NaN, Infinity]) {
    const d = evaluateHeadroom({
      messages,
      lastPromptTokens: bad as number | undefined,
      messagesSinceLastCall: 2,
      contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS,
      condenserTokenFraction: DEFAULT_CONDENSER_TOKEN_FRACTION,
    });
    check(`usage=${String(bad)} falls back without throwing`, d.usageSource === 'estimate' && Number.isFinite(d.promptTokensBefore));
  }

  const empty = evaluateHeadroom({ messages: [], contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS, condenserTokenFraction: 0.8 });
  check('empty conversation does not throw', empty.shouldCompact === false && empty.promptTokensBefore === 0);
}

// ---------------------------------------------------------------------------
// (d) No token budget → turn-count backstop, never silently unprotected
// ---------------------------------------------------------------------------

section('(d) unresolved budget → turn-count backstop');
{
  const messages = buildConversation(8, 40_000);
  for (const [window, fraction] of [[undefined, 0.8], [0, 0.8], [1_000_000, 0], [NaN, 0.8]] as const) {
    check(
      `window=${String(window)} fraction=${String(fraction)} resolves to no budget`,
      resolveThresholdTokens(window as number | undefined, fraction as number) === null,
    );
    const d = evaluateHeadroom({
      messages,
      lastPromptTokens: 10,
      contextWindowTokens: window as number | undefined,
      condenserTokenFraction: fraction as number,
    });
    check(`window=${String(window)} fraction=${String(fraction)} falls to the backstop`, d.trigger === 'turn-backstop');
  }

  const backstopped = compactMessages(messages, 5, DEFAULT_CONDENSER_KEEP_FIRST);
  check('backstop still compacts', backstopped !== messages);
  check('backstop respects keepFirst', JSON.stringify(backstopped[0]) === JSON.stringify(messages[0]));
  check('backstop leaves the last 2 turns whole', toolTextAt(backstopped, backstopped.length - 1).length === 40_003);
  check('backstop is inert in the first turns', compactMessages(messages, 1, DEFAULT_CONDENSER_KEEP_FIRST) === messages);

  const withBudget = evaluateHeadroom({
    messages,
    lastPromptTokens: 10,
    contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS,
    condenserTokenFraction: DEFAULT_CONDENSER_TOKEN_FRACTION,
  });
  check('with a budget, the turn count is not what fires', withBudget.trigger === 'token-budget' && withBudget.shouldCompact === false);
}

// ---------------------------------------------------------------------------
// (e) Reporting stays consistent with what is actually returned
// ---------------------------------------------------------------------------

section('(e) reporting consistency');
{
  // Tool results with no tool_call_id must still be counted as dropped —
  // droppedCount is what gates whether the dropped array is returned at all.
  const messages = buildConversation(8, 40_000).map((m: any) => {
    if (m.role !== 'tool') return m;
    const { tool_call_id, ...rest } = m;
    return rest as Message;
  });
  const promptTokensBefore = estimateMessageTokens(messages);
  const outcome = compactToBudget(messages, {
    promptTokensBefore,
    thresholdTokens: Math.floor(promptTokensBefore * 0.02),
    keepFirst: DEFAULT_CONDENSER_KEEP_FIRST,
  });
  check('drops without ids still counted', outcome.droppedCount > 0, outcome.droppedCount);
  check('drops without ids still applied to the returned array', outcome.messages !== messages);
  const droppedInArray = outcome.messages.filter(
    (m: any) => m.role === 'tool' && toolTextAt([m] as Message[], 0).startsWith('[Tool call output dropped'),
  ).length;
  check('droppedCount matches the array', droppedInArray === outcome.droppedCount, {
    droppedCount: outcome.droppedCount,
    droppedInArray,
  });
  check('savedChars is positive when changed', outcome.changed && outcome.savedChars > 0);

  // A projection must grow with everything appended since the last measurement,
  // so a turn that returned no usage cannot go unaccounted for.
  const convo = buildConversation(6, 30_000);
  const near = evaluateHeadroom({
    messages: convo,
    lastPromptTokens: 1000,
    messagesSinceLastCall: 2,
    contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS,
    condenserTokenFraction: DEFAULT_CONDENSER_TOKEN_FRACTION,
  });
  const far = evaluateHeadroom({
    messages: convo,
    lastPromptTokens: 1000,
    messagesSinceLastCall: 6,
    contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS,
    condenserTokenFraction: DEFAULT_CONDENSER_TOKEN_FRACTION,
  });
  check('projection grows with unmeasured turns', far.promptTokensBefore > near.promptTokensBefore, {
    near: near.promptTokensBefore,
    far: far.promptTokensBefore,
  });
}

// ---------------------------------------------------------------------------
// (f) keepFirst is honoured, and nonsense values cannot un-protect the head
// ---------------------------------------------------------------------------

section('(f) keepFirst handling');
{
  const messages = buildConversation(8, 40_000);
  const before = messages.map(m => JSON.stringify(m));
  const promptTokensBefore = estimateMessageTokens(messages);
  const thresholdTokens = Math.floor(promptTokensBefore * 0.5);

  const keep6 = compactToBudget(messages, { promptTokensBefore, thresholdTokens, keepFirst: 6 });
  check(
    'keepFirst=6 protects the first six messages',
    keep6.messages.slice(0, 6).every((m, i) => JSON.stringify(m) === before[i]),
  );
  check('keepFirst=6 still compacts what is left', keep6.changed === true);

  for (const bad of [-1, -100, 2.7]) {
    const r = compactToBudget(messages, { promptTokensBefore, thresholdTokens, keepFirst: bad });
    check(`keepFirst=${bad} does not throw and still compacts`, r.changed === true);
    check(`keepFirst=${bad} never reaches past the boundary`, r.messages.length === messages.length);
  }
  const fractional = compactToBudget(messages, { promptTokensBefore, thresholdTokens, keepFirst: 2.7 });
  check(
    'fractional keepFirst floors to 2 and keeps those two',
    fractional.messages.slice(0, 2).every((m, i) => JSON.stringify(m) === before[i]),
  );

  const huge = compactToBudget(messages, { promptTokensBefore, thresholdTokens, keepFirst: 10_000 });
  check('keepFirst past the conversation is a no-op', huge.changed === false && huge.messages === messages);
}

// ---------------------------------------------------------------------------
// (g) Multi-turn loop behaviour
// ---------------------------------------------------------------------------
//
// planCompaction is the same state machine runMcpAgent runs before every LLM
// call (agent-eval.ts, the `if (headroomEnabled)` block). Driving it over a
// synthetic run covers what single-call checks cannot: that the decision stays
// correct once compaction has already fired and the measured prompt therefore
// describes an already-reduced history.

section('(g) multi-turn loop behaviour');
{
  const CONTEXT = 100_000;
  const FRACTION = 0.8;
  const THRESHOLD = resolveThresholdTokens(CONTEXT, FRACTION)!;
  const RESULT_CHARS = 30_000;
  const TURNS = 24;

  /** Append one turn's growth: an assistant tool call plus its result. */
  function growByOneTurn(messages: Message[], t: number): void {
    messages.push({
      role: 'assistant',
      content: null,
      tool_calls: [{ id: `call_${t}`, type: 'function', function: { name: 'search', arguments: '{}' } }],
    } as unknown as Message);
    messages.push({
      role: 'tool',
      tool_call_id: `call_${t}`,
      content: [{ type: 'text', text: `T${t}:` + 'x'.repeat(RESULT_CHARS) }],
    } as unknown as Message);
  }

  /**
   * Drive planCompaction the way the loop does — plan, persist, send, then
   * commit the anchor only when the provider reported usage. The stand-in
   * provider reports exactly what our estimator computes for the prompt it was
   * handed, so these assertions are about the state machine, not estimator drift.
   */
  function runTurns(opts: { usageMissingOn?: Set<number>; budget?: boolean; context?: number } = {}) {
    const { usageMissingOn = new Set<number>(), budget = true, context = CONTEXT } = opts;
    const allMessages = buildConversation(1, RESULT_CHARS);
    let lastPromptTokens: number | undefined;
    let lastPromptChars: number | undefined;
    let messageCountAtLastCall = 0;
    const sentSizes: number[] = [];
    const firedOn: number[] = [];
    const plans: ReturnType<typeof planCompaction>[] = [];

    for (let i = 0; i < TURNS; i++) {
      const plan = planCompaction(allMessages, {
        turnIndex: i,
        lastPromptTokens,
        lastPromptChars,
        messageCountAtLastCall,
        contextWindowTokens: budget ? context : undefined,
        condenserTokenFraction: FRACTION,
        keepFirst: DEFAULT_CONDENSER_KEEP_FIRST,
      });
      checkOnce(
        budget ? 'token budget drives the run' : 'no budget falls to the backstop',
        plan.decision.trigger === (budget ? 'token-budget' : 'turn-backstop'),
      );

      plans.push(plan);
      let messagesToSend = plan.messagesToSend;
      if (messagesToSend !== allMessages) {
        firedOn.push(i);
        // Persist, exactly as the loop does.
        for (let k = 0; k < allMessages.length; k++) allMessages[k] = messagesToSend[k];
        messagesToSend = allMessages;
      }

      const promptMessageCount = messagesToSend.length;
      const promptChars = messageChars(messagesToSend);
      const promptTokens = Math.ceil(promptChars / CHARS_PER_TOKEN);
      sentSizes.push(promptTokens);

      // Anchor and measurement commit together, and only when usage came back.
      if (!usageMissingOn.has(i)) {
        lastPromptTokens = promptTokens;
        lastPromptChars = promptChars;
        messageCountAtLastCall = promptMessageCount;
      }

      growByOneTurn(allMessages, i + 1);
    }
    return { allMessages, sentSizes, firedOn, plans };
  }

  const clean = runTurns();
  check('stays idle for the first turns', clean.firedOn.length > 0 && clean.firedOn[0] > 2, clean.firedOn.slice(0, 3));
  check('compaction does eventually fire', clean.firedOn.length > 0);
  check('every sent prompt stays inside the window', clean.sentSizes.every(t => t < CONTEXT), {
    max: Math.max(...clean.sentSizes),
    CONTEXT,
  });
  check('no prompt is ever sent above the threshold', Math.max(...clean.sentSizes) <= THRESHOLD, {
    max: Math.max(...clean.sentSizes),
    THRESHOLD,
  });
  check('compaction fires more than once over a long run', clean.firedOn.length >= 2, clean.firedOn);
  check('no messages are added or lost', clean.allMessages.length === 2 + (TURNS + 1) * 2, clean.allMessages.length);
  check(
    'keepFirst survives the whole run',
    JSON.stringify(clean.allMessages[0]).includes('SYSTEM PROMPT') &&
      JSON.stringify(clean.allMessages[1]).includes('TASK STATEMENT'),
  );
  check(
    'the newest turn is never reduced',
    toolTextAt(clean.allMessages, clean.allMessages.length - 1).length === RESULT_CHARS + `T${TURNS}:`.length,
  );

  // Turns whose provider returned no usage must not lose their growth: the
  // anchor stays put, so the next projection still covers them.
  const gappy = runTurns({ usageMissingOn: new Set([5, 6, 7, 12, 13, 18, 19, 20]) });
  check('missing usage does not break the run', gappy.sentSizes.every(t => Number.isFinite(t) && t > 0));
  check('missing usage still keeps prompts inside the window', gappy.sentSizes.every(t => t < CONTEXT), {
    max: Math.max(...gappy.sentSizes),
    CONTEXT,
  });
  check('missing usage never sends above the threshold either', Math.max(...gappy.sentSizes) <= THRESHOLD, {
    max: Math.max(...gappy.sentSizes),
    THRESHOLD,
  });

  // With no resolvable budget the backstop must still bound the conversation.
  const noBudget = runTurns({ budget: false });
  check('backstop bounds the conversation without a budget', Math.max(...noBudget.sentSizes) < CONTEXT, {
    max: Math.max(...noBudget.sentSizes),
  });

  // A window smaller than the two turns we always keep whole cannot be met —
  // the incompressible floor is those turns. The contract there is to reduce as
  // hard as the rules allow and *report* the shortfall, never to quietly break
  // keepFirst or the recent turns, and never to claim it fits.
  const tight = runTurns({ context: 12_000 });
  const tightThreshold = resolveThresholdTokens(12_000, FRACTION)!;
  const tightOutcomes = tight.plans.map(p => p.outcome).filter(Boolean) as NonNullable<
    ReturnType<typeof planCompaction>['outcome']
  >[];
  const shortfalls = tightOutcomes.filter(o => o.changed && !o.underThreshold);
  check('escalation reaches the tightest cap', tightOutcomes.some(o => o.capApplied === 200), {
    caps: [...new Set(tightOutcomes.map(o => o.capApplied))],
  });
  check('escalation reaches outright drops', tightOutcomes.some(o => o.droppedCount > 0), {
    dropped: Math.max(0, ...tightOutcomes.map(o => o.droppedCount)),
  });
  check('an unreachable threshold is reported, not hidden', shortfalls.length > 0, shortfalls.length);
  check(
    'the shortfall is bounded by the turns we promise to keep whole',
    Math.max(...tight.sentSizes) <= Math.ceil((RESULT_CHARS * 2) / CHARS_PER_TOKEN) + tightThreshold,
    { max: Math.max(...tight.sentSizes), floor: Math.ceil((RESULT_CHARS * 2) / CHARS_PER_TOKEN) },
  );
  check('escalation fires on most turns of a tight run', tight.firedOn.length >= TURNS - 3, tight.firedOn.length);
  check('escalation still preserves keepFirst', JSON.stringify(tight.allMessages[0]).includes('SYSTEM PROMPT'));
  check(
    'escalation still leaves the newest turn whole',
    toolTextAt(tight.allMessages, tight.allMessages.length - 1).length === RESULT_CHARS + `T${TURNS}:`.length,
  );
  check('escalation never loses a message', tight.allMessages.length === 2 + (TURNS + 1) * 2);
}

// ---------------------------------------------------------------------------
// (h) chars-per-token calibrates to the provider
// ---------------------------------------------------------------------------

section('(h) chars-per-token calibration');
{
  check('no measurement → the documented default', calibrateCharsPerToken(undefined, undefined) === CHARS_PER_TOKEN);
  check('a real measurement is used verbatim', calibrateCharsPerToken(39_000, 10_000) === 3.9);
  for (const [chars, tokens, why] of [
    [0, 100, 'zero chars'],
    [100, 0, 'zero tokens'],
    [-5, 100, 'negative chars'],
    [100, -5, 'negative tokens'],
    [NaN, 100, 'NaN chars'],
    [100, NaN, 'NaN tokens'],
    [Infinity, 100, 'infinite chars'],
    [100, 99, 'implausibly dense (~1.0)'],
    [100_000, 100, 'implausibly sparse (1000)'],
  ] as [number, number, string][]) {
    check(`${why} → falls back to the default`, calibrateCharsPerToken(chars, tokens) === CHARS_PER_TOKEN);
  }

  // The whole point: a provider that bills differently from our constant is
  // tracked, so the projection stops carrying a systematic bias.
  const messages = buildConversation(8, 40_000);
  const PROVIDER = 4.6;
  const trueTokens = Math.ceil(messageChars(messages) / PROVIDER);
  const calibrated = calibrateCharsPerToken(messageChars(messages), trueTokens);
  check('calibration recovers the provider ratio', Math.abs(calibrated - PROVIDER) < 0.01, calibrated);

  const naive = compactToBudget(messages, {
    promptTokensBefore: trueTokens,
    thresholdTokens: Math.floor(trueTokens * 0.5),
  });
  const tuned = compactToBudget(messages, {
    promptTokensBefore: trueTokens,
    thresholdTokens: Math.floor(trueTokens * 0.5),
    charsPerToken: calibrated,
  });
  const actualAfter = Math.ceil(messageChars(tuned.messages) / PROVIDER);
  const naiveErr = Math.abs(naive.estimatedTokensAfter - actualAfter);
  const tunedErr = Math.abs(tuned.estimatedTokensAfter - actualAfter);
  check('calibrated projection beats the constant', tunedErr < naiveErr, { naiveErr, tunedErr, actualAfter });
  check('calibrated projection is within 1% of truth', tunedErr <= Math.ceil(actualAfter * 0.01), {
    tunedErr,
    actualAfter,
  });
  check('the decision reports the ratio it used', evaluateHeadroom({
    messages,
    contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS,
    condenserTokenFraction: DEFAULT_CONDENSER_TOKEN_FRACTION,
    charsPerToken: calibrated,
  }).charsPerToken === calibrated);
}

// ---------------------------------------------------------------------------
// (i) Multimodal content
// ---------------------------------------------------------------------------
//
// On a scanned-document task the images ARE the evidence — nothing in them can
// be recovered from a note about how many bytes were discarded. They also cost
// a flat per-item price, so discarding one buys almost nothing. Both facts have
// to hold: reduction never touches them, and their payload never inflates the
// char count that decides whether reduction happens at all.

section('(i) multimodal content');
{
  const b64 = 'data:image/png;base64,' + 'A'.repeat(700_000);
  const imageItem = { type: 'image', image_url: { url: b64 } };

  function withScans(turns: number, captionChars: number): Message[] {
    const messages: Message[] = [
      { role: 'system', content: 'SYSTEM PROMPT' } as unknown as Message,
      { role: 'user', content: 'TASK STATEMENT' } as unknown as Message,
    ];
    for (let t = 0; t < turns; t++) {
      messages.push({
        role: 'assistant', content: null,
        tool_calls: [{ id: `scan_${t}`, type: 'function', function: { name: 'read_page_scan', arguments: '{}' } }],
      } as unknown as Message);
      messages.push({
        role: 'tool', tool_call_id: `scan_${t}`,
        content: [{ type: 'text', text: `scan page ${t} `.padEnd(captionChars, '.') }, imageItem],
      } as unknown as Message);
    }
    return messages;
  }

  const countImages = (ms: Message[]) =>
    ms.reduce((n, m: any) => n + (Array.isArray(m.content) ? m.content.filter((c: any) => c?.type === 'image').length : 0), 0);

  // Measurement keeps the two apart.
  const scans = withScans(6, 120);
  const size = measurePrompt(scans);
  check('image payloads are excluded from the char count', size.textChars < 20_000, size.textChars);
  check('images are counted as items', size.imageCount === 6, size.imageCount);
  check('images are priced per item, not per byte',
    estimateMessageTokens(scans) < 6 * IMAGE_TOKENS_ESTIMATE + 20_000, estimateMessageTokens(scans));
  check('a 700KB scan is not mistaken for ~200k tokens',
    estimateMessageTokens(scans) < 30_000, estimateMessageTokens(scans));

  // Reduction leaves them alone — with a short caption (nothing to reclaim)
  // and with a long one (text truncated, image still there).
  for (const captionChars of [120, 5_000]) {
    const messages = withScans(6, captionChars);
    const before = countImages(messages);
    const out = compactToBudget(messages, {
      promptTokensBefore: 400_000,
      thresholdTokens: 1_000,       // unreachable: forces the full escalation
      keepFirst: DEFAULT_CONDENSER_KEEP_FIRST,
    });
    const after = countImages(out.messages);
    check(`caption ${captionChars}: every image survives reduction`, after === before, { before, after });
    check(`caption ${captionChars}: images keep their payload`,
      out.messages.every((m: any) => !Array.isArray(m.content) ||
        m.content.filter((c: any) => c?.type === 'image').every((c: any) => c.image_url?.url?.length > 100_000)));
    check(`caption ${captionChars}: tool results keep their tool_call_id`,
      out.messages.every((m: any) => m.role !== 'tool' || !!m.tool_call_id));
  }

  // Calibration must stay usable on a multimodal prompt: bill the images out
  // first, or the measured ratio lands in the hundreds and is rejected forever.
  const measured = measurePrompt(withScans(8, 200));
  const providerTokens = Math.ceil(measured.textChars / 3.9) + measured.imageCount * IMAGE_TOKENS_ESTIMATE;
  const naive = calibrateCharsPerToken(measured.textChars, providerTokens);           // images not billed out
  const aware = calibrateCharsPerToken(measured.textChars, providerTokens, measured.imageCount);
  check('ignoring images makes calibration unusable', naive === CHARS_PER_TOKEN, naive);
  check('billing images out recovers the text ratio', Math.abs(aware - 3.9) < 0.15, aware);
}

// ---------------------------------------------------------------------------
// (j) Nothing reducible — the case that must not be silent
// ---------------------------------------------------------------------------

section('(j) over budget with nothing reducible');
{
  // An opening prompt larger than the window: over budget, but every message
  // is inside keepFirst, so no reduction is possible. planCompaction must
  // still report shouldCompact so the caller can say so rather than sending a
  // doomed request without comment.
  const huge: Message[] = [
    { role: 'system', content: 'S'.repeat(200) } as unknown as Message,
    { role: 'user', content: 'U'.repeat(8_000_000) } as unknown as Message,
  ];
  const plan = planCompaction(huge, {
    turnIndex: 0,
    contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS,
    condenserTokenFraction: DEFAULT_CONDENSER_TOKEN_FRACTION,
    keepFirst: DEFAULT_CONDENSER_KEEP_FIRST,
  });
  check('the overflow is detected', plan.decision.shouldCompact === true);
  check('the projection exceeds the window', plan.decision.promptTokensBefore > DEFAULT_CONTEXT_WINDOW_TOKENS,
    plan.decision.promptTokensBefore);
  check('nothing is reducible', plan.outcome !== null && plan.outcome.changed === false);
  check('the shortfall is reported, not claimed as a fit', plan.outcome?.underThreshold === false);
  check('the array comes back untouched', plan.messagesToSend === huge);

  // Non-text content types survive reduction, not just images.
  const odd = { type: 'resource', resource: { uri: 'file:///e.bin', blob: 'X'.repeat(50_000) } };
  const msgs: Message[] = [
    { role: 'system', content: 's' } as unknown as Message,
    { role: 'user', content: 'u' } as unknown as Message,
  ];
  for (let i = 0; i < 6; i++) {
    msgs.push({ role: 'assistant', content: null,
      tool_calls: [{ id: `t${i}`, type: 'function', function: { name: 'f', arguments: '{}' } }] } as unknown as Message);
    msgs.push({ role: 'tool', tool_call_id: `t${i}`,
      content: [{ type: 'text', text: 'z'.repeat(9_000) }, odd] } as unknown as Message);
  }
  const out = compactToBudget(msgs, { promptTokensBefore: 500_000, thresholdTokens: 500, keepFirst: 2 });
  const kept = out.messages.filter((m: any) =>
    Array.isArray(m.content) && m.content.some((c: any) => c?.type === 'resource')).length;
  check('unknown non-text items survive reduction', kept === 6, { kept, truncated: out.truncatedCount, dropped: out.droppedCount });
  check('their payload is intact', out.messages.every((m: any) => !Array.isArray(m.content) ||
    m.content.filter((c: any) => c?.type === 'resource').every((c: any) => c.resource?.blob?.length === 50_000)));
}

// ---------------------------------------------------------------------------
// (k) Summarizing condenser
// ---------------------------------------------------------------------------

section('(k) summarizing condenser');
{
  const messages = buildConversation(8, 40_000);
  const req = buildSummaryRequest(messages, DEFAULT_CONDENSER_KEEP_FIRST);
  check('a summary request is built', req !== null);
  check('it spans only reducible turns', req!.spanStart === DEFAULT_CONDENSER_KEEP_FIRST &&
    req!.spanEnd === messages.length - 4, { start: req!.spanStart, end: req!.spanEnd });
  check('it names the results it will replace', req!.reducibleToolIndices.length === 6,
    req!.reducibleToolIndices.length);
  check('the summarizer is sent system + transcript', req!.messages.length === 2);
  check('the transcript carries the tool output', JSON.stringify(req!.messages).includes('T0:'));

  const summary = 'FINDINGS: total 85,980.\nACTIONS: read pages.\nDECISIONS: excluded estimate.\nOUTSTANDING: none.';
  const folded = applySummary(messages, summary, req!);
  check('message count is unchanged', folded.length === messages.length);
  check('every tool result keeps its tool_call_id',
    folded.every((m: any) => m.role !== 'tool' || !!m.tool_call_id));
  check('the summary lands in the conversation', JSON.stringify(folded).includes('FINDINGS: total 85,980'));
  check('it appears exactly once', JSON.stringify(folded).split('FINDINGS: total 85,980').length - 1 === 1);
  check('keepFirst is untouched',
    JSON.stringify(folded[0]) === JSON.stringify(messages[0]) &&
    JSON.stringify(folded[1]) === JSON.stringify(messages[1]));
  check('the last 2 turns are untouched',
    folded.slice(-4).every((m, i) => JSON.stringify(m) === JSON.stringify(messages[messages.length - 4 + i])));
  // What remains is the protected floor — keepFirst plus the last two turns —
  // plus the summary itself. Everything reducible is gone.
  const floorChars = messageChars(messages.slice(0, DEFAULT_CONDENSER_KEEP_FIRST))
    + messageChars(messages.slice(-4));
  check('it collapses to the protected floor plus the summary',
    messageChars(folded) < floorChars + summary.length + 2_000,
    { after: messageChars(folded), floorChars });
  check('that is a >70% reduction here',
    messageChars(folded) < messageChars(messages) * 0.3,
    { before: messageChars(messages), after: messageChars(folded) });

  // Images must survive being summarized, just as they survive truncation.
  const withImage: Message[] = messages.map((m: any, i) =>
    m.role === 'tool' && i === 3
      ? { ...m, content: [...m.content, { type: 'image', image_url: { url: 'data:image/png;base64,' + 'A'.repeat(400_000) } }] }
      : m) as Message[];
  const req2 = buildSummaryRequest(withImage, DEFAULT_CONDENSER_KEEP_FIRST)!;
  check('image payloads are not sent to the summarizer',
    !JSON.stringify(req2.messages).includes('A'.repeat(1000)));
  check('the summarizer is told an image was retained',
    JSON.stringify(req2.messages).includes('retained separately'));
  const folded2 = applySummary(withImage, summary, req2);
  const imgs = folded2.filter((m: any) => Array.isArray(m.content) && m.content.some((c: any) => c?.type === 'image')).length;
  check('the image survives summarization', imgs === 1, imgs);

  // Nothing old enough to condense -> no request, so the caller falls back.
  check('a short conversation yields no request', buildSummaryRequest(buildConversation(1, 5_000), 2) === null);
  check('an empty conversation yields no request', buildSummaryRequest([], 2) === null);
}

// ---------------------------------------------------------------------------
// (l) The off switch is real
// ---------------------------------------------------------------------------

section('(l) off switch');
{
  check('omitted → off', isHeadroomEnabled(undefined) === false);
  check("'off' → off", isHeadroomEnabled('off') === false);
  check("'compact' → on (back-compat)", isHeadroomEnabled('compact') === true);
  check("'headroom' → on", isHeadroomEnabled('headroom') === true);
}

// ---------------------------------------------------------------------------

console.log(`\n${checks - failures}/${checks} checks passed`);
if (failures > 0) {
  console.error(`${failures} check(s) failed`);
  process.exit(1);
}
