"use client";

import { createContext, useContext, useState } from "react";

/** A question the agent is waiting on. Resolving it resumes the paused model turn. */
export interface PendingDecision {
  toolCallId: string;
  question: string;
  choices: string[];
  allowFreeform: boolean;
  settle: (answer: string) => void;
  cancel: () => void;
}

export const DecisionContext = createContext<PendingDecision | null>(null);

/**
 * Approval calls restored from history that the hosted agent may still be
 * holding (the page was reloaded mid-approval). Answering one starts the
 * continuation run that resolves the paused call.
 */
export interface ResumableCalls {
  pending: ReadonlySet<string>;
  respond: (toolCallId: string, content: string) => void;
}

export const ResumeContext = createContext<ResumableCalls>({ pending: new Set(), respond: () => {} });

interface AskUserArgs {
  question?: string;
  choices?: string[];
  allowFreeform?: boolean;
}

/**
 * The agent's `ask_user` call: approvals before write actions, clarifications.
 * Interactive while its call is pending; afterwards it shows the answer that was
 * returned to the agent. The same decision is mirrored in the run inspector.
 */
export function AskUserCard({
  toolCallId,
  args,
  status,
  result,
  variant = "inline",
}: {
  toolCallId: string;
  args: AskUserArgs;
  status: string;
  result?: string;
  variant?: "inline" | "panel";
}) {
  const pending = useContext(DecisionContext);
  const resume = useContext(ResumeContext);
  const inSession = pending && pending.toolCallId === toolCallId ? pending : null;
  // A question restored from history that the agent is still waiting on.
  const restored = !inSession && result === undefined && resume.pending.has(toolCallId);
  const live = inSession
    ? inSession
    : restored
      ? { settle: (answer: string) => resume.respond(toolCallId, answer) }
      : null;
  const [answer, setAnswer] = useState("");
  const choices = args.choices ?? [];
  const allowFreeform = args.allowFreeform ?? true;
  const done = !restored && (status === "complete" || (!live && result !== undefined));

  return (
    <div
      data-testid={variant === "panel" ? "decision-panel" : "decision-card"}
      data-state={live ? "pending" : done ? "answered" : "waiting"}
      className={`border rounded-xl p-4 transition-colors duration-200 ${
        live ? "bg-ask-bg border-ask shadow-sm" : done ? "bg-surface border-border-soft" : "bg-ask-bg border-ask-border"
      } ${variant === "inline" ? "max-w-2xl" : ""}`}
    >
      <div className="flex items-start gap-3 mb-3">
        <p className="flex-1 text-sm font-medium text-text-strong whitespace-pre-wrap">{args.question || "…"}</p>
        <span
          className={`flex-shrink-0 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${
            live ? "bg-ask text-accent-fg" : "bg-surface text-muted border border-border-soft"
          }`}
        >
          {live && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
          {live ? "Needs you" : done ? "Answered" : "Waiting"}
        </span>
      </div>

      {done ? (
        <p className="text-sm text-text" data-testid="decision-answer">
          <span className="text-muted">Answer: </span>
          <span className="font-medium">{result || "(no answer)"}</span>
        </p>
      ) : live ? (
        <>
          {choices.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {choices.map((choice) => (
                <button
                  key={choice}
                  type="button"
                  data-testid="decision-choice"
                  onClick={() => live.settle(choice)}
                  className="px-3.5 py-1.5 text-sm bg-surface text-text border border-border rounded-lg hover:bg-hover hover:border-ask transition-all"
                >
                  {choice}
                </button>
              ))}
            </div>
          )}
          {allowFreeform && (
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (answer.trim()) live.settle(answer.trim());
              }}
            >
              <input
                type="text"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="Type your answer…"
                aria-label="Your answer"
                className="flex-1 text-sm text-text bg-surface border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ask placeholder:text-muted"
              />
              <button
                type="submit"
                disabled={!answer.trim()}
                className="px-4 py-2 text-sm bg-ask text-accent-fg rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity font-medium"
              >
                Send
              </button>
            </form>
          )}
        </>
      ) : (
        <p className="text-xs text-muted">Preparing the question…</p>
      )}
    </div>
  );
}
