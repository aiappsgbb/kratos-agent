"use client";

import { useState } from "react";
import { generateEvalScenarios, upsertEvalScenario } from "@/lib/api";
import type { EvalScenario } from "@/types";

interface Props {
  useCase: string;
  open: boolean;
  onClose: () => void;
  onGenerated: (scenarios: EvalScenario[]) => void;
}

export function GenerateScenariosModal({ useCase, open, onClose, onGenerated }: Props): JSX.Element | null {
  const [count, setCount] = useState(10);
  const [instructions, setInstructions] = useState("");
  const [drafts, setDrafts] = useState<EvalScenario[]>([]);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  const handleGenerate = async () => {
    setGenerating(true);
    setError("");
    setDrafts([]);
    try {
      const result = await generateEvalScenarios(useCase, { count, instructions: instructions || undefined, persist: false });
      setDrafts(result.scenarios);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate scenarios");
    } finally {
      setGenerating(false);
    }
  };

  const updateDraft = (idx: number, patch: Partial<EvalScenario>) => {
    setDrafts((prev) => prev.map((d, i) => (i === idx ? { ...d, ...patch } : d)));
  };

  const removeDraft = (idx: number) => {
    setDrafts((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSaveAll = async () => {
    if (drafts.length === 0) return;
    setSaving(true);
    setError("");
    try {
      const saved: EvalScenario[] = [];
      for (const scenario of drafts) {
        const s = await upsertEvalScenario(useCase, scenario);
        saved.push(s);
      }
      onGenerated(saved);
      onClose();
      setDrafts([]);
      setInstructions("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save scenarios");
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    if (!generating && !saving) {
      setDrafts([]);
      setInstructions("");
      setError("");
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in"
      onClick={handleClose}
    >
      <div
        className="bg-surface rounded-2xl shadow-card max-w-2xl w-full border border-border-soft animate-slide-up flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-soft flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-accent flex items-center justify-center border border-accent">
              <svg className="w-4 h-4 text-accent-fg" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-semibold text-text">Generate Scenarios</h2>
              <p className="text-xs text-muted">AI-generated eval scenarios for <span className="font-mono">{useCase}</span></p>
            </div>
          </div>
          <button
            onClick={handleClose}
            disabled={generating || saving}
            className="p-2 text-muted hover:text-text hover:bg-hover rounded-lg transition-all disabled:opacity-40"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {error && (
            <div className="px-4 py-3 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 text-sm rounded-xl border border-red-100 dark:border-red-500/20 flex items-center justify-between">
              <span>{error}</span>
              <button onClick={() => setError("")} className="text-red-400 hover:text-red-600 transition-colors ml-3">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          {/* Generation params */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-text mb-1.5">
                Number of scenarios
              </label>
              <input
                type="number"
                min={1}
                max={50}
                value={count}
                onChange={(e) => setCount(Math.max(1, parseInt(e.target.value, 10) || 1))}
                className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all"
              />
            </div>
            <div className="col-span-2">
              <label className="block text-sm font-medium text-text mb-1.5">
                Instructions <span className="text-muted font-normal">(optional)</span>
              </label>
              <textarea
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                rows={2}
                placeholder="Focus on edge cases around authentication flows..."
                className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all resize-none"
              />
            </div>
          </div>

          <div>
            <button
              onClick={handleGenerate}
              disabled={generating || saving}
              className="flex items-center gap-2 px-5 py-2.5 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {generating ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-white/30 border-t-white" />
                  Generating…
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                  </svg>
                  Generate Draft
                </>
              )}
            </button>
          </div>

          {/* Draft list */}
          {drafts.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-text">
                  Draft scenarios <span className="font-mono text-xs text-muted">({drafts.length})</span>
                </h3>
                <p className="text-xs text-muted">Edit inline or remove before saving</p>
              </div>
              {drafts.map((scenario, idx) => (
                <div
                  key={idx}
                  className="border border-border-soft rounded-xl p-4 space-y-3 bg-surface-2"
                >
                  <div className="flex items-start justify-between gap-3">
                    <input
                      type="text"
                      value={scenario.name}
                      onChange={(e) => updateDraft(idx, { name: e.target.value })}
                      className="flex-1 px-2.5 py-1.5 bg-surface border border-border-soft rounded-lg text-sm font-medium text-text focus:outline-none focus:ring-1 focus:ring-accent"
                      placeholder="Scenario name"
                    />
                    <button
                      onClick={() => removeDraft(idx)}
                      className="p-1.5 text-muted hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-lg transition-all"
                      title="Remove"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                  <textarea
                    value={scenario.input_message}
                    onChange={(e) => updateDraft(idx, { input_message: e.target.value })}
                    rows={2}
                    placeholder="Input message…"
                    className="w-full px-2.5 py-1.5 bg-surface border border-border-soft rounded-lg text-sm text-text focus:outline-none focus:ring-1 focus:ring-accent resize-none"
                  />
                  <textarea
                    value={scenario.expected_behavior}
                    onChange={(e) => updateDraft(idx, { expected_behavior: e.target.value })}
                    rows={2}
                    placeholder="Expected behavior…"
                    className="w-full px-2.5 py-1.5 bg-surface border border-border-soft rounded-lg text-sm text-text focus:outline-none focus:ring-1 focus:ring-accent resize-none"
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-soft flex-shrink-0">
          <button
            onClick={handleClose}
            disabled={generating || saving}
            className="px-4 py-2 text-sm text-muted bg-surface-2 border border-border-soft rounded-xl hover:bg-hover transition-all font-medium disabled:opacity-40"
          >
            Cancel
          </button>
          {drafts.length > 0 && (
            <button
              onClick={handleSaveAll}
              disabled={saving || generating}
              className="flex items-center gap-2 px-5 py-2 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium disabled:opacity-50"
            >
              {saving ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-white/30 border-t-white" />
                  Saving…
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                  Save All ({drafts.length})
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
