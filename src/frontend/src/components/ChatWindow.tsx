"use client";

import { useState, useRef, useEffect } from "react";
import { Conversation, ChatMessage, ToolCallInfo, RunStats, Attachment } from "@/types";
import { streamAgentChat, getConversationMessages, updateConversation } from "@/lib/api";
import { MessageBubble } from "./MessageBubble";
import { ThoughtChain } from "./ThoughtChain";

interface UserInputPrompt {
  requestId: string;
  question: string;
  choices: string[];
  allowFreeform: boolean;
}

interface Props {
  conversation: Conversation;
  onTitleChange?: (conversationId: string, title: string) => void;
  initialMessage?: string;
  onOpenSidebar?: () => void;
}

export function ChatWindow({ conversation, onTitleChange, initialMessage, onOpenSidebar }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [thoughts, setThoughts] = useState<string[]>([]);
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCallInfo[]>([]);
  const [runStats, setRunStats] = useState<RunStats | null>(null);
  const [messageStats, setMessageStats] = useState<Record<string, { thoughts: string[]; toolCalls: ToolCallInfo[]; runStats: RunStats }>>({});
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [userInputPrompt, setUserInputPrompt] = useState<UserInputPrompt | null>(null);
  const [userInputAnswer, setUserInputAnswer] = useState("");
  const [followUpQuestions, setFollowUpQuestions] = useState<string[]>([]);
  // True when an answer is being generated on the backend but is not being
  // streamed into this view (e.g. after navigating back to a conversation
  // whose response is still in flight). We poll Cosmos until it arrives.
  const [awaitingResponse, setAwaitingResponse] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const thoughtsRef = useRef<string[]>([]);
  const toolCallsRef = useRef<ToolCallInfo[]>([]);
  const runStatsRef = useRef<RunStats | null>(null);
  const titleUpdatedRef = useRef<Set<string>>(new Set()); // track which conversations have been titled
  const isStreamingRef = useRef(false);
  isStreamingRef.current = isStreaming;

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thoughts, activeToolCalls, runStats]);

  // Load message history when switching to an existing conversation. The agent
  // run is durable on the backend (it persists to Cosmos even if the client
  // disconnects), so if the latest message is still a user turn we poll until
  // the assistant response is persisted and appears.
  useEffect(() => {
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    const MAX_ATTEMPTS = 150; // ~5 min at 2s intervals
    const POLL_INTERVAL_MS = 2000;

    setMessages([]);
    setThoughts([]);
    setActiveToolCalls([]);
    setRunStats(null);
    setMessageStats({});
    setAwaitingResponse(false);

    const applyLoaded = (loaded: ChatMessage[]) => {
      setMessages(loaded);
      const restoredStats: Record<string, { thoughts: string[]; toolCalls: ToolCallInfo[]; runStats: RunStats }> = {};
      for (const m of loaded) {
        if (m.role === "assistant" && m.metadata?.runStats) {
          restoredStats[m.id] = {
            thoughts: m.metadata.thoughts || [],
            toolCalls: m.metadata.toolCalls || [],
            runStats: m.metadata.runStats,
          };
        }
      }
      setMessageStats(restoredStats);
    };

    const load = async () => {
      try {
        const msgs = await getConversationMessages(conversation.id);
        if (cancelled) return;
        // If this view is actively streaming its own response, leave it alone.
        if (isStreamingRef.current) {
          setAwaitingResponse(false);
          return;
        }
        const loaded = (msgs as ChatMessage[]).filter(
          (m) => m.role === "user" || m.role === "assistant"
        );
        if (loaded.length > 0) {
          applyLoaded(loaded);
        }
        // A trailing user message means the assistant reply is still being
        // generated on the backend — keep polling until it shows up.
        const last = loaded[loaded.length - 1];
        const pending = !!last && last.role === "user";
        setAwaitingResponse(pending);
        if (pending && attempts < MAX_ATTEMPTS) {
          attempts += 1;
          pollTimer = setTimeout(load, POLL_INTERVAL_MS);
        }
      } catch {
        // Non-fatal — new conversation or backend briefly unreachable.
      }
    };

    load();

    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [conversation.id]);

  const handleSend = async (messageOverride?: string) => {
    const trimmed = (messageOverride ?? input).trim();
    if (!trimmed || isStreaming) return;

    // Auto-title on the first message of a conversation
    const isFirstMessage = messages.length === 0;
    if (isFirstMessage && !titleUpdatedRef.current.has(conversation.id)) {
      titleUpdatedRef.current.add(conversation.id);
      const title = trimmed.slice(0, 60) + (trimmed.length > 60 ? "…" : "");
      onTitleChange?.(conversation.id, title);
      updateConversation(conversation.id, { title }).catch(() => {/* non-fatal */});
    }

    // Add user message
    const currentAttachments = attachments.length > 0 ? [...attachments] : undefined;
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      conversationId: conversation.id,
      role: "user",
      content: trimmed,
      attachments: currentAttachments,
      createdAt: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);
    setAwaitingResponse(false);
    setThoughts([]);
    setActiveToolCalls([]);
    setRunStats(null);
    setFollowUpQuestions([]);
    thoughtsRef.current = [];
    toolCallsRef.current = [];
    runStatsRef.current = null;

    setAttachments([]);

    let assistantContent = "";

    // Create a placeholder assistant message
    const assistantId = crypto.randomUUID();

    await streamAgentChat(
      conversation.id,
      trimmed,
      (event) => {
        const data = event.data as Record<string, unknown>;

        switch (event.type) {
          case "thought":
            setThoughts((prev) => {
              const next = [...prev, data.content as string];
              thoughtsRef.current = next;
              return next;
            });
            break;

          case "tool_call":
            setActiveToolCalls((prev) => {
              const toolCall: ToolCallInfo = {
                skillName: data.skillName as string,
                status: data.status as "started" | "completed" | "failed",
                input: data.input as string,
                output: data.output as string,
                durationMs: data.durationMs as number,
                source: (data.source as string | undefined) ?? undefined,
              };
              let next: ToolCallInfo[];
              if (toolCall.status !== "started") {
                // Find the first "started" entry with the same name and update it
                const existing = prev.findIndex(
                  (tc) =>
                    tc.skillName === toolCall.skillName &&
                    tc.status === "started"
                );
                if (existing >= 0) {
                  next = [...prev];
                  next[existing] = { ...next[existing], ...toolCall };
                } else {
                  // Fallback: find any entry with the same name
                  const fallback = prev.findIndex(
                    (tc) => tc.skillName === toolCall.skillName
                  );
                  if (fallback >= 0) {
                    next = [...prev];
                    next[fallback] = { ...next[fallback], ...toolCall };
                  } else {
                    next = [...prev, toolCall];
                  }
                }
              } else {
                next = [...prev, toolCall];
              }
              toolCallsRef.current = next;
              return next;
            });
            break;

          case "content":
            assistantContent += data.content as string;
            setMessages((prev) => {
              const existing = prev.find((m) => m.id === assistantId);
              if (existing) {
                return prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: assistantContent }
                    : m
                );
              }
              return [
                ...prev,
                {
                  id: assistantId,
                  conversationId: conversation.id,
                  role: "assistant" as const,
                  content: assistantContent,
                  createdAt: new Date().toISOString(),
                },
              ];
            });
            break;

          case "error":
            setMessages((prev) => [
              ...prev,
              {
                id: crypto.randomUUID(),
                conversationId: conversation.id,
                role: "assistant" as const,
                content: `Error: ${data.message}`,
                createdAt: new Date().toISOString(),
              },
            ]);
            break;

          case "done": {
            const stats: RunStats = {
              totalDurationMs: (data.totalDurationMs as number) || 0,
              totalToolCalls: (data.totalToolCalls as number) || 0,
              promptTokens: (data.promptTokens as number) || 0,
              completionTokens: (data.completionTokens as number) || 0,
              reasoningTokens: (data.reasoningTokens as number) || 0,
              totalTokens: (data.totalTokens as number) || 0,
              timeToFirstTokenMs: (data.timeToFirstTokenMs as number) || 0,
              modelLatencyMs: (data.modelLatencyMs as number) || 0,
            };
            setRunStats(stats);
            runStatsRef.current = stats;
            break;
          }

          case "user_input_request": {
            setUserInputPrompt({
              requestId: data.requestId as string,
              question: data.question as string,
              choices: (data.choices as string[]) || [],
              allowFreeform: (data.allowFreeform as boolean) ?? true,
            });
            break;
          }

          case "follow_up_questions": {
            const questions = (data.questions as string[]) || [];
            if (questions.length > 0) {
              setFollowUpQuestions(questions);
            }
            break;
          }
        }
      },
      (error) => {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            conversationId: conversation.id,
            role: "assistant" as const,
            content: `Connection error: ${error.message}`,
            createdAt: new Date().toISOString(),
          },
        ]);
        setIsStreaming(false);
      },
      () => {
        // Persist execution details for this assistant message
        if (runStatsRef.current) {
          setMessageStats((prev) => ({
            ...prev,
            [assistantId]: {
              thoughts: thoughtsRef.current,
              toolCalls: toolCallsRef.current,
              runStats: runStatsRef.current!,
            },
          }));
        }
        setIsStreaming(false);
        setUserInputPrompt(null);
      },
      currentAttachments,
      conversation.useCase
    );
  };

  // Auto-send initial message (e.g. from sample question click)
  const handleSendRef = useRef(handleSend);
  handleSendRef.current = handleSend;
  const initialMessageSentRef = useRef<string | null>(null);
  useEffect(() => {
    if (initialMessage && initialMessageSentRef.current !== `${conversation.id}:${initialMessage}` && messages.length === 0) {
      initialMessageSentRef.current = `${conversation.id}:${initialMessage}`;
      const timer = setTimeout(() => handleSendRef.current(initialMessage), 150);
      return () => clearTimeout(timer);
    }
  }, [conversation.id, initialMessage, messages.length]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const newAttachments: Attachment[] = await Promise.all(
      Array.from(files).map(
        (file) =>
          new Promise<Attachment>((resolve) => {
            const reader = new FileReader();
            reader.onload = () => {
              const base64 = (reader.result as string).split(",")[1] || "";
              resolve({
                type: "file" as const,
                path: file.name,
                displayName: file.name,
                content: base64,
              });
            };
            reader.readAsDataURL(file);
          })
      )
    );
    setAttachments((prev) => [...prev, ...newAttachments]);
    // Reset the input so the same file can be selected again
    e.target.value = "";
  };

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const handleUserInputSubmit = async (answer: string) => {
    if (!userInputPrompt) return;
    // In hosted-agent mode there is no side-channel to push an answer into a
    // running Foundry invocation, so the answer is sent as a normal follow-up
    // message. The backend reuses the persisted gateway session for this
    // conversation, which resumes the same hosted-agent container.
    setUserInputPrompt(null);
    setUserInputAnswer("");
    await handleSend(answer);
  };

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* Header */}
      <header className="border-b border-border-soft px-4 sm:px-6 py-3 bg-surface backdrop-blur sticky top-0 z-10 shadow-sm">
        <div className="flex items-center gap-3 max-w-5xl mx-auto">
          {/* Mobile hamburger */}
          {onOpenSidebar && (
            <button
              onClick={onOpenSidebar}
              className="lg:hidden p-2 -ml-1 text-muted hover:text-text rounded-lg hover:bg-slate-100/80 transition-all flex-shrink-0"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              </svg>
            </button>
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5">
              <h2 className="text-sm font-semibold text-text truncate">
                {conversation.title}
              </h2>
              {conversation.useCase && conversation.useCase !== "generic" && (
                <span className="text-[10px] px-2 py-0.5 bg-accent-soft text-accent rounded-full font-medium flex-shrink-0">
                  {conversation.useCase.replace(/-/g, " ")}
                </span>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-3 sm:px-4 py-4 sm:py-6">
        <div className="max-w-5xl mx-auto space-y-5">
          {messages.map((msg) => (
            <div key={msg.id}>
              <MessageBubble message={msg} />
              {/* Show persisted execution details below each assistant message */}
              {msg.role === "assistant" && messageStats[msg.id] && (
                <div className="mt-2 ml-11">
                  <ThoughtChain
                    thoughts={messageStats[msg.id].thoughts}
                    toolCalls={messageStats[msg.id].toolCalls}
                    isStreaming={false}
                    runStats={messageStats[msg.id].runStats}
                  />
                </div>
              )}
            </div>
          ))}

          {/* Live thought chain (visible during streaming) */}
          {isStreaming && (thoughts.length > 0 || activeToolCalls.length > 0) && (
            <div className="ml-11">
              <ThoughtChain
                thoughts={thoughts}
                toolCalls={activeToolCalls}
                isStreaming={true}
                runStats={runStats}
              />
            </div>
          )}

          {/* Awaiting a response that is still being generated on the backend
              (e.g. after navigating back to this conversation mid-run). */}
          {!isStreaming && awaitingResponse && (
            <div className="ml-11 flex items-center gap-2.5 text-sm text-slate-500 dark:text-slate-400">
              <svg className="w-4 h-4 animate-spin text-primary-500" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>Generating response…</span>
            </div>
          )}

          {/* User input request from agent — themed with ask-* tokens */}
          {userInputPrompt && (
            <div className="ml-11 bg-ask-bg border border-ask-border border-l-[3px] border-l-ask rounded-xl p-4 max-w-2xl">
              <p className="text-sm font-medium text-text-strong mb-3">
                {userInputPrompt.question}
              </p>
              {userInputPrompt.choices.length > 0 && (
                <div className="flex flex-wrap gap-2 mb-3">
                  {userInputPrompt.choices.map((choice) => (
                    <button
                      key={choice}
                      onClick={() => handleUserInputSubmit(choice)}
                      className="px-3.5 py-1.5 text-sm bg-surface text-text border border-border rounded-lg hover:bg-hover hover:border-ask transition-all"
                    >
                      {choice}
                    </button>
                  ))}
                </div>
              )}
              {userInputPrompt.allowFreeform && (
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={userInputAnswer}
                    onChange={(e) => setUserInputAnswer(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && userInputAnswer.trim()) {
                        handleUserInputSubmit(userInputAnswer.trim());
                      }
                    }}
                    placeholder="Type your answer..."
                    className="flex-1 text-sm text-text bg-surface border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ask placeholder:text-muted"
                  />
                  <button
                    onClick={() => handleUserInputSubmit(userInputAnswer.trim())}
                    disabled={!userInputAnswer.trim()}
                    className="px-4 py-2 text-sm bg-ask text-accent-fg rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity font-medium"
                  >
                    Send
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Follow-up question suggestions */}
          {!isStreaming && followUpQuestions.length > 0 && (
            <div className="ml-11 animate-fade-in">
              <div className="flex items-center gap-2 mb-2.5">
                <div className="w-5 h-5 rounded-md bg-accent dark:from-violet-500/20 dark:to-primary-500/20 flex items-center justify-center">
                  <svg className="w-3 h-3 text-accent" viewBox="0 0 24 24" fill="currentColor">
                    <path fillRule="evenodd" d="M14.615 1.595a.75.75 0 01.359.852L12.982 9.75h7.268a.75.75 0 01.548 1.262l-10.5 11.25a.75.75 0 01-1.272-.71l1.992-7.302H3.75a.75.75 0 01-.548-1.262l10.5-11.25a.75.75 0 01.913-.143z" clipRule="evenodd" />
                  </svg>
                </div>
                <span className="text-xs font-medium text-muted uppercase tracking-wider">Continue exploring</span>
              </div>
              <div className="flex flex-col gap-1.5 stagger-children">
                {followUpQuestions.map((question, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                      setFollowUpQuestions([]);
                      handleSend(question);
                    }}
                    className="group flex items-center gap-3 px-3.5 py-2.5 text-[13px] text-left rounded-xl border border-transparent hover:bg-hover hover:border-border hover:shadow-sm transition-all duration-300 animate-slide-up-stagger active:scale-[0.98]"
                  >
                    <svg className="w-4 h-4 text-text-strong group-hover:text-primary-500 transition-colors flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                    </svg>
                    <span className="text-muted group-hover:text-slate-800 dark:group-hover:text-slate-200 transition-colors">
                      {question}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Attachment pills */}
      {attachments.length > 0 && (
        <div className="px-4">
          <div className="max-w-5xl mx-auto px-2 py-2 flex flex-wrap gap-2">
            {attachments.map((att, idx) => (
              <span
                key={idx}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-surface border border-border-soft rounded-lg shadow-sm animate-fade-in"
              >
                <svg className="w-3.5 h-3.5 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
                <span className="text-text font-medium">{att.displayName || ("path" in att ? att.path : "")}</span>
                <button
                  onClick={() => removeAttachment(idx)}
                  className="ml-0.5 text-muted hover:text-red-400 transition-colors"
                >
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="px-3 sm:px-4 pb-4 sm:pb-5 pt-2">
        <div className="max-w-5xl mx-auto">
          <div className="flex items-end gap-2 bg-surface rounded-2xl border border-border-soft px-3 py-2 focus-within:border-primary-400/60 dark:focus-within:border-primary-500/40 focus-within:shadow-[0_0_0_3px_rgba(99,102,241,0.1),0_4px_16px_rgba(0,0,0,0.04)] shadow-lg transition-all duration-300">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={handleFileSelect}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming}
              title="Attach files"
              className="p-2 text-muted hover:text-accent rounded-lg hover:bg-hover transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed active:scale-95"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" />
              </svg>
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask me anything..."
              rows={1}
              disabled={isStreaming}
              className="flex-1 resize-none text-sm text-text placeholder:text-muted bg-transparent border-none focus:outline-none focus:ring-0 py-2 px-1 disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ minHeight: "36px", maxHeight: "200px" }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = "auto";
                target.style.height = Math.min(target.scrollHeight, 200) + "px";
              }}
            />
            <button
              onClick={() => handleSend()}
              disabled={isStreaming || !input.trim()}
              aria-label={isStreaming ? "Sending message" : "Send message"}
              className="p-2.5 bg-accent text-accent-fg rounded-xl transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed shadow-md hover:shadow-lg active:scale-95"
            >
              {isStreaming ? (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
