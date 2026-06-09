"use client";

import { useState, useEffect } from "react";

import { getApiUrl } from "@/lib/config";

interface AIServiceStatus {
  configured: boolean;
  foundryEndpoint: string;
  foundryModelDeployment: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export function SettingsModal({ open, onClose }: Props) {
  const [endpoint, setEndpoint] = useState("");
  const [model, setModel] = useState("gpt-52");
  const [status, setStatus] = useState<AIServiceStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  // Load current settings on open
  useEffect(() => {
    if (!open) return;
    fetch(`${getApiUrl()}/api/settings`)
      .then((res) => res.json())
      .then((data: AIServiceStatus) => {
        setStatus(data);
        setEndpoint(data.foundryEndpoint || "");
        setModel(data.foundryModelDeployment || "gpt-52");
      })
      .catch(() => {
        setStatus(null);
      });
  }, [open]);

  const handleSave = async () => {
    setSaving(true);
    setMessage("");
    try {
      const res = await fetch(`${getApiUrl()}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          foundryEndpoint: endpoint,
          foundryModelDeployment: model,
        }),
      });
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      const data: AIServiceStatus = await res.json();
      setStatus(data);
      setMessage("Settings saved successfully!");
    } catch (err) {
      setMessage(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in" onClick={onClose}>
      <div className="bg-surface rounded-2xl shadow-card max-w-lg w-full border border-border-soft animate-slide-up" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-soft">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-accent from-slate-100 to-slate-50 dark:from-white/[0.08] dark:to-white/[0.04] flex items-center justify-center border border-border-soft">
              <svg className="w-4.5 h-4.5 text-text" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-semibold text-text">AI Service Configuration</h2>
              <p className="text-xs text-muted">Bring your own keys &amp; endpoints</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-muted hover:text-text hover:bg-hover rounded-lg transition-all"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-5">
          <p className="text-sm text-muted leading-relaxed">
            Configure the Microsoft Foundry endpoint and model deployment. Authentication uses Managed Identity — no API keys needed.
          </p>

          {/* Status indicator */}
          {status && (
            <div className={`flex items-center gap-2.5 text-sm px-4 py-2.5 rounded-xl ${
              status.configured
                ? "bg-emerald-50 text-emerald-700 border border-emerald-100"
                : "bg-amber-50 text-amber-700 border border-amber-100"
            }`}>
              <span className={`w-2.5 h-2.5 rounded-full ${
                status.configured ? "bg-emerald-500" : "bg-amber-500"
              }`} />
              <span className="font-medium">{status.configured ? "Endpoint configured" : "No endpoint configured"}</span>
            </div>
          )}

          {/* Foundry Endpoint */}
          <div>
            <label className="block text-sm font-medium text-text mb-1.5">
              Foundry Endpoint
            </label>
            <input
              type="url"
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="https://your-resource.services.ai.azure.com"
              className="w-full px-4 py-2.5 bg-surface-2 border border-border-soft rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all placeholder:text-muted"
            />
          </div>

          {/* Model Deployment */}
          <div>
            <label className="block text-sm font-medium text-text mb-1.5">
              Model Deployment
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-52"
              className="w-full px-4 py-2.5 bg-surface-2 border border-border-soft rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all placeholder:text-muted"
            />
          </div>

          {/* Message */}
          {message && (
            <div className={`text-sm px-4 py-2.5 rounded-xl ${message.startsWith("Error") ? "text-red-600 bg-red-50 border border-red-100" : "text-emerald-600 bg-emerald-50 border border-emerald-100"}`}>
              {message}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-6 py-4 border-t border-border-soft bg-surface-2 rounded-b-2xl">
          <button
            onClick={onClose}
            className="px-5 py-2.5 text-sm text-text bg-surface border border-border-soft rounded-xl hover:bg-hover transition-all font-medium"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2.5 text-sm text-accent-fg bg-accent rounded-xl transition-all disabled:opacity-50 font-medium shadow-sm"
          >
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
