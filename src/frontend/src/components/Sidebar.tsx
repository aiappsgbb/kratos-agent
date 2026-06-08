"use client";

import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { Conversation, UseCase } from "@/types";
import { useTheme } from "./ThemeProvider";

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = Math.max(0, now - then);
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Group label for a conversation date */
function getDateGroup(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return "This Week";
  if (diffDays < 30) return "This Month";
  return "Older";
}

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  onNew: () => void;
  onSelect: (conv: Conversation) => void;
  onDelete: (conv: Conversation) => void;
  onOpenSettings: () => void;
  onOpenSkills: () => void;
  onOpenAgenticLoop: () => void;
  useCases: UseCase[];
  selectedUseCase: string;
  onSelectUseCase: (name: string) => void;
  onCloseMobile?: () => void;
}

export function Sidebar({ conversations, activeId, onNew, onSelect, onDelete, onOpenSettings, onOpenSkills, onOpenAgenticLoop, useCases, selectedUseCase, onSelectUseCase, onCloseMobile }: Props) {
  const { theme, toggleTheme } = useTheme();
  const [searchQuery, setSearchQuery] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [personaFilter, setPersonaFilter] = useState<"curated" | "all">("curated");

  // Filter the persona dropdown by the curated toggle. Fall back to "all" if
  // a "curated" filter would leave the dropdown empty (e.g. dev branch without
  // any curated personas marked yet).
  const curatedUseCases = useCases.filter((uc) => uc.curated === true);
  const effectiveFilter =
    personaFilter === "curated" && curatedUseCases.length === 0 ? "all" : personaFilter;
  const visibleUseCases =
    effectiveFilter === "curated" ? curatedUseCases : useCases;

  // If the toggle hides the currently selected persona, snap back to the
  // first visible one so the dropdown never shows a stale empty value.
  useEffect(() => {
    if (visibleUseCases.length === 0) return;
    if (!visibleUseCases.some((uc) => uc.name === selectedUseCase)) {
      onSelectUseCase(visibleUseCases[0].name);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveFilter, useCases.length]);

  // Filter conversations by selected persona and search query
  const personaConversations = conversations.filter(
    (c) => c.useCase === selectedUseCase
  );
  const filteredConversations = searchQuery.trim()
    ? personaConversations.filter((c) =>
        c.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : personaConversations;

  // Group conversations by date
  const grouped: { label: string; convs: Conversation[] }[] = [];
  const seen = new Set<string>();
  for (const conv of filteredConversations) {
    const label = getDateGroup(conv.updatedAt || conv.createdAt);
    if (!seen.has(label)) {
      seen.add(label);
      grouped.push({ label, convs: [] });
    }
    grouped.find((g) => g.label === label)!.convs.push(conv);
  }

  const handleConfirmDelete = () => {
    if (deleteTarget) {
      onDelete(deleteTarget);
      setDeleteTarget(null);
    }
  };

  return (
    <aside className="w-[300px] bg-navy-950 flex flex-col h-full border-r border-white/[0.06]" aria-label="Conversation sidebar">
      {/* Delete confirmation dialog — portal to body to escape sidebar transform containment */}
      {deleteTarget && createPortal(
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-md animate-fade-in">
          <div className="bg-navy-900 border border-white/[0.1] rounded-2xl p-6 max-w-sm mx-4 shadow-2xl animate-scale-in ring-1 ring-white/[0.05]">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center flex-shrink-0">
                <svg className="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
              </div>
              <h3 className="text-base font-semibold text-white">Delete conversation?</h3>
            </div>
            <p className="text-xs text-slate-400 mb-2 leading-relaxed">
              This will permanently delete:
            </p>
            <p className="text-sm text-slate-200 font-medium break-words mb-5 px-3 py-2 bg-white/[0.04] rounded-lg border border-white/[0.06]">
              {deleteTarget.title}
            </p>
            <div className="flex gap-2.5 justify-end">
              <button
                onClick={() => setDeleteTarget(null)}
                className="px-4 py-2 text-sm text-slate-300 hover:text-white hover:bg-white/[0.08] rounded-lg transition-all duration-200"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                className="px-4 py-2 text-sm text-white bg-red-600 hover:bg-red-500 rounded-lg transition-all duration-200 shadow-lg shadow-red-500/20 active:scale-95"
              >
                Delete
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
      {/* Logo / brand */}
      <div className="px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-gradient-to-br from-violet-600 via-primary-500 to-cyan-400 rounded-xl flex items-center justify-center shadow-lg shadow-primary-500/20 flex-shrink-0 ring-1 ring-white/10">
            <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="currentColor">
              <path fillRule="evenodd" d="M14.615 1.595a.75.75 0 01.359.852L12.982 9.75h7.268a.75.75 0 01.548 1.262l-10.5 11.25a.75.75 0 01-1.272-.71l1.992-7.302H3.75a.75.75 0 01-.548-1.262l10.5-11.25a.75.75 0 01.913-.143z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="flex-1 min-w-0">
            <span className="font-semibold text-white text-sm tracking-tight">
              Kratos Agent
            </span>
            <p className="text-[11px] text-slate-400">AI Solution Accelerator</p>
          </div>
          {/* Mobile close button */}
          {onCloseMobile && (
            <button
              onClick={onCloseMobile}
              className="lg:hidden p-1.5 text-slate-500 hover:text-slate-300 rounded-lg hover:bg-white/[0.06] transition-all"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Use-case selector */}
      {useCases.length > 1 && (
        <div className="px-3 py-2">
          <label className="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5 px-1">
            Agent Persona
          </label>

          {/* Curated / All toggle — segmented control */}
          <div
            role="tablist"
            aria-label="Persona filter"
            className="flex items-center gap-0.5 mb-2 p-0.5 bg-white/[0.04] border border-white/[0.08] rounded-lg"
          >
            <button
              role="tab"
              aria-selected={effectiveFilter === "curated"}
              onClick={() => setPersonaFilter("curated")}
              disabled={curatedUseCases.length === 0}
              title={curatedUseCases.length === 0 ? "No curated personas available" : "Show only hand-curated, approved personas"}
              className={`flex-1 text-xs font-medium px-2 py-1.5 rounded-md transition-all ${
                effectiveFilter === "curated"
                  ? "bg-primary-500/20 text-primary-200 border border-primary-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]"
              } disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              Curated ({curatedUseCases.length})
            </button>
            <button
              role="tab"
              aria-selected={effectiveFilter === "all"}
              onClick={() => setPersonaFilter("all")}
              title="Show all personas including experimental / AI-generated ones"
              className={`flex-1 text-xs font-medium px-2 py-1.5 rounded-md transition-all ${
                effectiveFilter === "all"
                  ? "bg-primary-500/20 text-primary-200 border border-primary-500/30"
                  : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.04]"
              }`}
            >
              All ({useCases.length})
            </button>
          </div>

          <div className="relative">
            <select
              value={selectedUseCase}
              onChange={(e) => onSelectUseCase(e.target.value)}
              aria-label="Select agent persona"
              className="w-full text-sm text-slate-200 bg-white/[0.06] border border-white/[0.1] rounded-lg pl-3 pr-9 py-2.5 focus:outline-none focus:ring-1 focus:ring-primary-500/50 focus:border-primary-500/50 appearance-none cursor-pointer hover:bg-white/[0.1] hover:border-white/[0.14] transition-all"
            >
              {visibleUseCases.map((uc) => (
                <option key={uc.name} value={uc.name} className="bg-navy-900">
                  {uc.displayName} ({uc.skillCount} skills)
                </option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5">
              <svg className="w-4 h-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
              </svg>
            </div>
          </div>
        </div>
      )}

      {/* New conversation button */}
      <div className="px-3 pb-2">
        <button
          onClick={onNew}
          className="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-sm text-slate-200 bg-gradient-to-r from-primary-600/10 to-violet-600/10 border border-primary-500/20 rounded-xl hover:from-primary-600/20 hover:to-violet-600/20 hover:border-primary-500/30 transition-all duration-300 active:scale-[0.98] group"
        >
          <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-primary-500 to-violet-500 flex items-center justify-center shadow-sm shadow-primary-500/20 group-hover:shadow-md group-hover:shadow-primary-500/30 transition-all">
            <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
          </div>
          New conversation
        </button>
      </div>

      {/* Divider */}
      <div className="mx-4 my-1 border-t border-white/[0.06]" />

      {/* Search conversations */}
      {conversations.length > 0 && (
        <div className="px-3 py-2">
          <div className="relative">
            <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search conversations..."
              aria-label="Search conversations"
              className="w-full text-xs text-slate-200 bg-white/[0.04] border border-white/[0.08] rounded-lg pl-8 pr-8 py-2 focus:outline-none focus:ring-1 focus:ring-primary-500/50 focus:border-primary-500/50 placeholder:text-slate-500 transition-all"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-slate-500 hover:text-slate-300 transition-colors"
                aria-label="Clear search"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Conversation list */}
      <nav className="flex-1 overflow-y-auto dark-scrollbar px-2 py-1" aria-label="Conversations">
        {filteredConversations.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 px-4">
            <div className="w-10 h-10 rounded-xl bg-white/[0.04] flex items-center justify-center mb-3">
              <svg className="w-5 h-5 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
              </svg>
            </div>
            <p className="text-xs text-slate-600 text-center">
              {searchQuery ? "No matching conversations" : "No conversations yet"}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {grouped.map((group) => (
              <div key={group.label}>
                <div className="px-3 py-1">
                  <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
                    {group.label}
                  </span>
                </div>
                <ul className="space-y-0.5">
                  {group.convs.map((conv) => (
                    <li key={conv.id} className="animate-slide-in-left">
                      <div className={`group flex items-center rounded-xl transition-all duration-300 ${
                        activeId === conv.id
                          ? "bg-gradient-to-r from-primary-500/[0.15] to-violet-500/[0.10] border border-primary-500/25 shadow-sm shadow-primary-500/5"
                          : "hover:bg-white/[0.06] border border-transparent hover:border-white/[0.06]"
                      }`}>
                        <button
                          onClick={() => onSelect(conv)}
                          className="flex-1 min-w-0 text-left px-3 py-2.5"
                        >
                          <span className={`block truncate text-sm leading-snug ${
                            activeId === conv.id
                              ? "text-white font-medium"
                              : "text-slate-300"
                          }`}>
                            {conv.title}
                          </span>
                          <div className="flex items-center gap-2 mt-1">
                            {conv.useCase && conv.useCase !== "generic" && (
                              <span className={`text-[10px] px-1.5 py-0.5 rounded-md ${
                                activeId === conv.id
                                  ? "bg-primary-500/20 text-primary-300"
                                  : "bg-white/[0.04] text-slate-500"
                              }`}>
                                {conv.useCase.replace(/-/g, " ")}
                              </span>
                            )}
                            <span className="text-[10px] text-slate-500 tabular-nums">
                              {timeAgo(conv.updatedAt || conv.createdAt)}
                            </span>
                          </div>
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setDeleteTarget(conv); }}
                          className="opacity-0 group-hover:opacity-100 flex-shrink-0 p-1.5 mr-1.5 text-slate-600 hover:text-red-400 rounded-md transition-all"
                          title="Delete conversation"
                          aria-label={`Delete conversation: ${conv.title}`}
                        >
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </nav>

      {/* Footer */}
      <div className="px-2 py-3 border-t border-white/[0.06] space-y-0.5">
        <button
          onClick={onOpenSkills}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-slate-300 hover:text-white hover:bg-white/[0.06] rounded-xl transition-all duration-200 group active:scale-[0.98]"
        >
          <svg className="w-4 h-4 text-accent-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.991l1.004.827c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          Agent Manager
        </button>
        <button
          onClick={onOpenSettings}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-slate-300 hover:text-white hover:bg-white/[0.06] rounded-xl transition-all duration-200 group active:scale-[0.98]"
        >
          <svg className="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
          </svg>
          BYOK Settings
        </button>
        <button
          onClick={onOpenAgenticLoop}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-slate-300 hover:text-white hover:bg-white/[0.06] rounded-xl transition-all duration-200 group active:scale-[0.98]"
        >
          <svg className="w-4 h-4 text-primary-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
          </svg>
          How It Works
        </button>
        <div className="pt-2 px-3 flex items-center justify-between">
            <p className="text-[10px] text-slate-500 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-slow"></span>
            Copilot SDK + Foundry + MCP
          </p>
          <div className="flex items-center gap-1">
          <a
            href="https://github.com/kmavrodis/kratos-agent"
            target="_blank"
            rel="noopener noreferrer"
            className="p-1.5 text-slate-500 hover:text-slate-300 rounded-lg hover:bg-white/[0.06] transition-all"
            title="View on GitHub"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z"/>
            </svg>
          </a>
          <button
            onClick={toggleTheme}
            className="p-1.5 text-slate-500 hover:text-slate-300 rounded-lg hover:bg-white/[0.06] transition-all"
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? (
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
              </svg>
            ) : (
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
              </svg>
            )}
          </button>
          </div>
        </div>
      </div>
    </aside>
  );
}
