"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Message } from "@ag-ui/core";
import { CopilotKit, useAgent, useCopilotKit, useFrontendTool, useRenderTool } from "@copilotkit/react-core/v2";
import { z } from "zod";
import type { Conversation, RunStats, Skill } from "@/types";
import { getConversationMessages, updateConversation } from "@/lib/api";
import { getAuthConfig, getBasePath, getDemoMode } from "@/lib/config";
import { getMcpAccessToken } from "@/lib/auth";
import { speak, speakableText, stopSpeaking } from "@/lib/voice";
import {
  ASK_USER_TOOL,
  FOLLOW_UPS_EVENT,
  KRATOS_AGENT_ID,
  RUN_STATS_EVENT,
  historyToAgui,
  type PersistedMessage,
} from "@/lib/agui";
import { AskUserCard, DecisionContext, ResumeContext, type PendingDecision } from "./AskUserCard";
import { Composer, type ImageAttachment } from "./Composer";
import { MessageList } from "./MessageList";
import { RunInspector, type ActivityItem, type RunPhase } from "./RunInspector";
import { ToolCallChip } from "./ToolCallChip";
import { PROPOSE_ALLOCATION_TOOL, useKratosVisuals } from "./visuals";

/** Browser tools that pause the run until the user decides. */
const DECISION_TOOLS = new Set([ASK_USER_TOOL, PROPOSE_ALLOCATION_TOOL]);

function decisionSummary(toolName: string | undefined, content: string): string {
  if (toolName === PROPOSE_ALLOCATION_TOOL) {
    try {
      const d = JSON.parse(content) as { decision?: string; edited?: boolean };
      if (d.decision === "approved") return d.edited ? "You approved the allocation with edits" : "You approved the allocation";
      if (d.decision === "rejected") return "You rejected the allocation";
    } catch {
      // fall through
    }
  }
  return `You answered: ${content}`;
}

interface Props {
  conversation: Conversation;
  personaName: string;
  skills: Skill[];
  onTitleChange?: (conversationId: string, title: string) => void;
  initialMessage?: string;
  onOpenSidebar?: () => void;
}

const askUserParameters = z.object({
  question: z.string().describe("The question to ask, phrased for the user."),
  choices: z.array(z.string()).optional().describe("Answer options to offer, when the answer is one of a few."),
  allowFreeform: z.boolean().optional().describe("Whether the user may type their own answer. Defaults to true."),
});

/** Acquire the signed-in user's OBO token silently; never prompts (see lib/api). */
async function oboTokens(): Promise<Record<string, string>> {
  const cfg = getAuthConfig();
  if (!cfg) return {};
  try {
    const token = await getMcpAccessToken(false);
    return token ? { [cfg.mcpServerName]: token } : {};
  } catch {
    return {};
  }
}

/**
 * One conversation with a Kratos persona, on CopilotKit + AG-UI.
 *
 * The provider is keyed by conversation so each thread gets a fresh agent. The
 * persona (use case) and the user's OBO token travel to the backend as AG-UI
 * forwardedProps on every run, including the continuation run CopilotKit starts
 * after the user answers an `ask_user` question.
 */
export function AgentWorkspace(props: Props) {
  const [origin, setOrigin] = useState("");
  const [providerError, setProviderError] = useState("");
  const [mcpAccessTokens, setMcpAccessTokens] = useState<Record<string, string>>({});
  useEffect(() => setOrigin(`${window.location.origin}${getBasePath()}`), []);
  const properties = useMemo(
    () => ({ useCase: props.conversation.useCase, mcpAccessTokens }),
    [props.conversation.useCase, mcpAccessTokens],
  );

  if (!origin) {
    return <div className="flex-1 flex items-center justify-center text-sm text-muted" role="status">Connecting…</div>;
  }
  return (
    <CopilotKit
      key={props.conversation.id}
      runtimeUrl={`${origin}/copilotkit/${KRATOS_AGENT_ID}`}
      agent={KRATOS_AGENT_ID}
      useSingleEndpoint
      enableInspector={false}
      properties={properties}
      onError={(e) => setProviderError(e.error.message)}
    >
      <Workspace {...props} providerError={providerError} setMcpAccessTokens={setMcpAccessTokens} />
    </CopilotKit>
  );
}

function Workspace({
  conversation,
  personaName,
  skills,
  onTitleChange,
  initialMessage,
  onOpenSidebar,
  providerError,
  setMcpAccessTokens,
}: Props & { providerError: string; setMcpAccessTokens: (t: Record<string, string>) => void }) {
  const { agent, isReady } = useAgent({ agentId: KRATOS_AGENT_ID });
  const { copilotkit, executingToolCallIds } = useCopilotKit();

  const [hydrated, setHydrated] = useState(false);
  const [awaitingResponse, setAwaitingResponse] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [runStats, setRunStats] = useState<Record<string, RunStats>>({});
  const [lastRun, setLastRun] = useState<RunStats | null>(null);
  const [followUps, setFollowUps] = useState<string[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [decision, setDecision] = useState<PendingDecision | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  // Approval calls restored from history without an answer (page reloaded mid-approval).
  const [restoredPending, setRestoredPending] = useState<ReadonlySet<string>>(new Set());
  const titledRef = useRef(false);
  const initialSentRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Restore the thread from Cosmos. The backend run is detached from the HTTP
  // request, so a trailing user message means an answer is still being produced:
  // poll until it lands.
  useEffect(() => {
    if (!isReady) return;
    agent.threadId = conversation.id;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async (attempt: number) => {
      try {
        const history = (await getConversationMessages(conversation.id)) as PersistedMessage[];
        if (cancelled || agent.isRunning) return;
        if (history.length) {
          const restored = historyToAgui(history);
          agent.setMessages(restored.messages);
          setRunStats(restored.runStats);
          titledRef.current = true;
          const answered = new Set(restored.messages.flatMap((m) => (m.role === "tool" ? [m.toolCallId] : [])));
          setRestoredPending(
            new Set(
              restored.messages.flatMap((m) =>
                m.role === "assistant"
                  ? (m.toolCalls ?? []).filter((c) => DECISION_TOOLS.has(c.function.name) && !answered.has(c.id)).map((c) => c.id)
                  : [],
              ),
            ),
          );
        }
        const pending = history[history.length - 1]?.role === "user";
        setAwaitingResponse(pending);
        if (pending && attempt < 150) timer = setTimeout(() => void load(attempt + 1), 2000);
      } catch {
        // New conversation, or the backend is briefly unreachable.
      } finally {
        if (!cancelled) setHydrated(true);
      }
    };
    void load(0);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [isReady, agent, conversation.id]);

  // Live run telemetry for the inspector, straight off the AG-UI event stream.
  useEffect(() => {
    const now = () => Date.now();
    const close = (id: string, failed = false) =>
      setActivity((prev) => prev.map((a) => (a.id === id && a.endedAt === undefined ? { ...a, endedAt: now(), failed } : a)));
    const sub = agent.subscribe({
      onRunStartedEvent: () => {
        setError("");
        setFollowUps([]);
      },
      onTextMessageStartEvent: ({ event }) => {
        setActivity((prev) =>
          prev.some((a) => a.id === event.messageId)
            ? prev
            : [...prev, { id: event.messageId, kind: "text", name: "Writing the answer", startedAt: now() }],
        );
      },
      onTextMessageEndEvent: ({ event }) => close(event.messageId),
      onToolCallStartEvent: ({ event }) => {
        const decision = DECISION_TOOLS.has(event.toolCallName);
        setActivity((prev) => [
          ...prev,
          {
            id: event.toolCallId,
            kind: decision ? "decision" : "tool",
            name: decision ? "Waiting for your decision" : event.toolCallName,
            toolName: event.toolCallName,
            startedAt: now(),
          },
        ]);
      },
      onToolCallEndEvent: ({ event, toolCallArgs }) =>
        setActivity((prev) => prev.map((a) => (a.id === event.toolCallId ? { ...a, args: toolCallArgs } : a))),
      onToolCallResultEvent: ({ event }) => {
        setActivity((prev) =>
          prev.map((a) =>
            a.id === event.toolCallId && a.kind === "decision" ? { ...a, name: decisionSummary(a.toolName, event.content) } : a,
          ),
        );
        close(event.toolCallId);
      },
      onSubagentStartedEvent: ({ event }) =>
        setActivity((prev) => [...prev, { id: event.subagentRunId, kind: "subagent", name: event.name, startedAt: now() }]),
      onSubagentFinishedEvent: ({ event }) => close(event.subagentRunId),
      onSubagentErrorEvent: ({ event }) => close(event.subagentRunId, true),
      onCustomEvent: ({ event }) => {
        if (event.name === RUN_STATS_EVENT) {
          const stats = event.value as RunStats;
          setLastRun(stats);
          const lastAssistant = [...agent.messages].reverse().find((m) => m.role === "assistant");
          if (lastAssistant) setRunStats((prev) => ({ ...prev, [lastAssistant.id]: stats }));
        } else if (event.name === FOLLOW_UPS_EVENT) {
          const questions = (event.value as { questions?: string[] })?.questions ?? [];
          setFollowUps(questions.slice(0, 4));
        }
      },
      onRunErrorEvent: ({ event }) => setError(event.message || "The agent run failed."),
      onRunFailed: ({ error: e }) => setError(e.message || "The agent run failed."),
    });
    return () => sub.unsubscribe();
  }, [agent]);

  useEffect(() => {
    if (providerError) setError(providerError);
  }, [providerError]);

  // Every backend tool (skills, MCP tools, built-ins) renders as a live chip.
  useRenderTool(
    {
      agentId: KRATOS_AGENT_ID,
      name: "*",
      render: (p: { name: string; toolCallId: string; args?: unknown; parameters?: unknown; status: string; result?: string }) => (
        <ToolCallChip name={p.name} toolCallId={p.toolCallId} args={p.args ?? p.parameters} status={p.status} result={p.result} />
      ),
    },
    [],
  );

  // The persona skills' approval gate. The backend runtime suspends the model's
  // ask_user call; this handler waits for the user's answer (inline card or
  // inspector), and CopilotKit resumes the same model turn with it.
  useFrontendTool(
    {
      agentId: KRATOS_AGENT_ID,
      name: ASK_USER_TOOL,
      description:
        "Ask the user a question and wait for their answer. Use it to get approval before any action that writes, sends or changes something, and to clarify ambiguous requests. Offer choices when the answer is one of a few options.",
      parameters: askUserParameters,
      handler: (args, ctx) =>
        new Promise<string>((resolve, reject) => {
          let settled = false;
          const finish = () => {
            ctx.signal?.removeEventListener("abort", cancel);
            setDecision(null);
          };
          const settle = (answer: string) => {
            if (settled) return;
            settled = true;
            finish();
            resolve(answer);
          };
          const cancel = () => {
            if (settled) return;
            settled = true;
            finish();
            reject(new Error("The user stopped the run before answering."));
          };
          setDecision({
            toolCallId: ctx.toolCall.id,
            question: args.question ?? "",
            choices: args.choices ?? [],
            allowFreeform: args.allowFreeform ?? true,
            settle,
            cancel,
          });
          setInspectorOpen(true);
          ctx.signal?.addEventListener("abort", cancel, { once: true });
          if (ctx.signal?.aborted) cancel();
        }),
      render: (p: { toolCallId: string; args: Partial<z.infer<typeof askUserParameters>>; status: string; result?: string }) => (
        <div className="basis-full">
          <AskUserCard toolCallId={p.toolCallId} args={p.args} status={p.status} result={p.result} />
        </div>
      ),
    },
    [isReady, conversation.id],
  );

  useKratosVisuals([isReady, conversation.id]);

  // A human-in-the-loop card (e.g. a rebalance proposal) is waiting when its
  // call has no result yet and the run has handed off to the browser.
  const answeredCalls = new Set(agent.messages.filter((m) => m.role === "tool").map((m) => (m as { toolCallId: string }).toolCallId));
  const pendingCard = !agent.isRunning && agent.messages.some(
    (m) => m.role === "assistant" && (m.toolCalls ?? []).some((c) => c.function.name === PROPOSE_ALLOCATION_TOOL && !answeredCalls.has(c.id)),
  );
  const waiting = !!decision || pendingCard || restoredPending.size > 0;
  const busy = agent.isRunning || executingToolCallIds.size > 0 || submitting;
  const phase: RunPhase = !isReady || !hydrated ? "connecting" : waiting ? "waiting" : busy || awaitingResponse ? "working" : error ? "error" : "ready";

  const send = useCallback(
    async (text: string, images: ImageAttachment[] = []) => {
      if (!isReady || busy || !text.trim()) return;
      setSubmitting(true);
      setError("");
      setFollowUps([]);
      setActivity([]);
      setAwaitingResponse(false);

      if (!titledRef.current && agent.messages.length === 0) {
        titledRef.current = true;
        const title = text.slice(0, 60) + (text.length > 60 ? "…" : "");
        onTitleChange?.(conversation.id, title);
        updateConversation(conversation.id, { title }).catch(() => {});
      }

      const tokens = await oboTokens();
      setMcpAccessTokens(tokens);
      agent.threadId = conversation.id;
      agent.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: images.length
          ? [{ type: "text", text }, ...images.map((img) => ({ type: "binary" as const, mimeType: img.mimeType, data: img.data, filename: img.filename }))]
          : text,
      } as Message);
      try {
        await copilotkit.runAgent({ agent, forwardedProps: { useCase: conversation.useCase, mcpAccessTokens: tokens } });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setSubmitting(false);
      }
    },
    [agent, busy, conversation.id, conversation.useCase, copilotkit, isReady, onTitleChange, setMcpAccessTokens],
  );

  // Answer an approval restored from history: the tool message resolves the
  // call the hosted agent is still holding, and the model continues its turn.
  const resume = useMemo(
    () => ({
      pending: restoredPending,
      respond: (toolCallId: string, content: string) => {
        setRestoredPending((prev) => {
          const next = new Set(prev);
          next.delete(toolCallId);
          return next;
        });
        setError("");
        setSubmitting(true);
        agent.addMessage({ id: crypto.randomUUID(), role: "tool", toolCallId, content } as Message);
        void oboTokens()
          .then((tokens) => {
            setMcpAccessTokens(tokens);
            return copilotkit.runAgent({ agent, forwardedProps: { useCase: conversation.useCase, mcpAccessTokens: tokens } });
          })
          .catch((e) => setError(e instanceof Error ? e.message : String(e)))
          .finally(() => setSubmitting(false));
      },
    }),
    [restoredPending, agent, copilotkit, conversation.useCase, setMcpAccessTokens],
  );

  const stop = useCallback(async () => {
    decision?.cancel();
    try {
      await copilotkit.stopAgent({ agent });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [agent, copilotkit, decision]);

  // Auto-send the sample question that opened this conversation.
  useEffect(() => {
    if (!initialMessage || initialSentRef.current || !hydrated || agent.messages.length > 0) return;
    initialSentRef.current = true;
    void send(initialMessage);
  }, [initialMessage, hydrated, agent.messages.length, send]);

  const messages = agent.messages;
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, decision, followUps.length]);

  // Read-aloud: speak each finished answer and any question put to the user.
  const [readAloud, setReadAloud] = useState(false);
  useEffect(() => setReadAloud(localStorage.getItem("kratos.readAloud") === "1"), []);
  const toggleReadAloud = () => {
    const next = !readAloud;
    setReadAloud(next);
    localStorage.setItem("kratos.readAloud", next ? "1" : "0");
    if (!next) stopSpeaking();
  };
  const prevPhase = useRef<RunPhase>(phase);
  useEffect(() => {
    const was = prevPhase.current;
    prevPhase.current = phase;
    if (!readAloud || was !== "working" || phase !== "ready") return;
    const answer = [...agent.messages].reverse().find((m) => m.role === "assistant" && typeof m.content === "string" && m.content.trim());
    if (answer) speak(speakableText(answer.content as string));
  }, [phase, readAloud, agent]);
  useEffect(() => {
    if (readAloud && decision?.question) speak(decision.question);
  }, [decision?.question, readAloud]);

  const last = messages[messages.length - 1];
  const showThinking = (busy || awaitingResponse) && !waiting && (!last || last.role === "user" || last.role === "tool");

  const inspector = (
    <RunInspector
      phase={phase}
      decision={decision}
      activity={activity}
      lastRun={lastRun}
      personaName={personaName}
      skills={skills}
      error={error}
      onClose={() => setInspectorOpen(false)}
    />
  );

  return (
    <ResumeContext.Provider value={resume}>
    <DecisionContext.Provider value={decision}>
      <div className="flex h-full min-h-0" data-testid="agent-workspace" data-thread-id={conversation.id}>
        <section className="flex-1 flex flex-col min-w-0 bg-bg">
          <header className="border-b border-border-soft px-4 sm:px-6 py-3 bg-surface sticky top-0 z-10 shadow-sm">
            <div className="flex items-center gap-3 max-w-4xl mx-auto">
              {onOpenSidebar && (
                <button
                  type="button"
                  onClick={onOpenSidebar}
                  aria-label="Open sidebar"
                  className="lg:hidden p-2 -ml-1 text-muted hover:text-text rounded-lg hover:bg-hover transition-colors flex-shrink-0"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
                  </svg>
                </button>
              )}
              <div className="flex-1 min-w-0 flex items-center gap-2.5">
                <h1 className="text-sm font-semibold text-text truncate">{conversation.title}</h1>
                {getDemoMode() === "mock" && (
                  <span
                    data-testid="mock-badge"
                    title="Answers come from a scripted offline model, not a live LLM."
                    className="text-[11px] px-2 py-0.5 rounded-full font-medium flex-shrink-0 border border-border text-muted"
                  >
                    Mock model
                  </span>
                )}
                {conversation.useCase !== "generic" && (
                  <span className="text-[11px] px-2 py-0.5 bg-accent-soft text-accent rounded-full font-medium flex-shrink-0">{personaName}</span>
                )}
              </div>
              <button
                type="button"
                onClick={toggleReadAloud}
                aria-pressed={readAloud}
                aria-label={readAloud ? "Stop reading answers aloud" : "Read answers aloud"}
                title={readAloud ? "Reading answers aloud" : "Read answers aloud"}
                data-testid="read-aloud"
                className={`p-1.5 rounded-lg border transition-colors ${
                  readAloud ? "border-accent text-accent bg-accent-soft" : "border-border-soft text-muted hover:text-text hover:bg-hover"
                }`}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  {readAloud ? (
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
                  ) : (
                    <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 9.75L19.5 12m0 0l2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6l4.72-4.72a.75.75 0 011.28.531V19.94a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.506-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.395C2.806 8.757 3.63 8.25 4.51 8.25H6.75z" />
                  )}
                </svg>
              </button>
              <button
                type="button"
                onClick={() => setInspectorOpen((v) => !v)}
                aria-pressed={inspectorOpen}
                data-testid="toggle-inspector"
                className={`xl:hidden inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg border transition-colors ${
                  phase === "waiting" ? "border-ask text-ask" : "border-border-soft text-muted hover:text-text hover:bg-hover"
                }`}
              >
                {phase === "waiting" && <span className="w-1.5 h-1.5 rounded-full bg-ask animate-pulse" />}
                Run
              </button>
            </div>
          </header>

          <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 sm:px-4 py-4 sm:py-6">
            <div className="max-w-4xl mx-auto space-y-5" aria-live="polite">
              <MessageList messages={messages} conversationId={conversation.id} runStats={runStats} />

              {showThinking && (
                <div className="ml-11 flex items-center gap-2.5 text-sm text-muted" data-testid="thinking">
                  <span className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse [animation-delay:-0.4s]" />
                    <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse [animation-delay:-0.2s]" />
                    <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
                  </span>
                  {awaitingResponse && !busy ? "Still working on your last message…" : "Thinking…"}
                </div>
              )}

              {error && !busy && (
                <div role="alert" className="ml-11 max-w-2xl text-sm rounded-xl border border-red-200 bg-red-50 text-red-700 dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-300 px-4 py-3">
                  {error}
                </div>
              )}

              {!busy && followUps.length > 0 && (
                <div className="ml-11 animate-fade-in" data-testid="follow-ups">
                  <p className="text-xs font-medium text-muted mb-2">Continue with</p>
                  <div className="flex flex-col gap-1.5 items-start">
                    {followUps.map((q) => (
                      <button
                        key={q}
                        type="button"
                        onClick={() => void send(q)}
                        className="text-left text-[13px] px-3.5 py-2 rounded-xl border border-border-soft bg-surface text-text hover:border-accent hover:text-text-strong transition-colors duration-200"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <Composer disabled={!isReady || !hydrated || restoredPending.size > 0} busy={busy} waitingForDecision={waiting} canStop={agent.isRunning || !!decision} onSend={(t, imgs) => void send(t, imgs)} onStop={() => void stop()} />
        </section>

        {inspectorOpen && (
          <div className="xl:hidden fixed inset-0 z-30 bg-black/30" aria-hidden="true" onClick={() => setInspectorOpen(false)} />
        )}
        <div
          className={`${
            inspectorOpen ? "fixed inset-y-0 right-0 z-40 flex shadow-2xl" : "hidden"
          } xl:static xl:z-auto xl:flex xl:shadow-none`}
        >
          {inspector}
        </div>
      </div>
    </DecisionContext.Provider>
    </ResumeContext.Provider>
  );
}
