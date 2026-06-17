"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { ChatWindow } from "@/components/ChatWindow";
import { Sidebar } from "@/components/Sidebar";
import { SettingsModal } from "@/components/SettingsModal";
import { SkillsAdminPanel } from "@/components/SkillsAdminPanel";
import AgentLoop from "@/components/AgentLoop";
import { Conversation, UseCase, Skill } from "@/types";
import { listUseCases, listConversations, createConversation, deleteConversation, listSkills, importPersona } from "@/lib/api";
import { loadRuntimeConfig } from "@/lib/config";
import { readEmbedParams, takeImportManifest, settlePersonaUrl, type EmbedParams } from "@/lib/embed";
import { useTheme, THEMES, type ThemeName, type Mode } from "@/components/ThemeProvider";

type ImportStatus = "idle" | "importing" | "error" | "done";

const THEME_NAMES = new Set(THEMES.map((t) => t.id));

export default function Home() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] =
    useState<Conversation | null>(null);
  const [landingInput, setLandingInput] = useState("");
  const landingInputRef = useRef<HTMLTextAreaElement>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [skillsOpen, setSkillsOpen] = useState(false);
  const [useCases, setUseCases] = useState<UseCase[]>([]);
  const [selectedUseCase, setSelectedUseCase] = useState<string>("generic");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [agenticLoopOpen, setAgenticLoopOpen] = useState(false);
  const [configReady, setConfigReady] = useState(false);

  // Embed mode (chromeless hosting under another origin — design spec §C)
  const [embed, setEmbed] = useState<EmbedParams>({
    embed: false, theme: null, mode: null, persona: null, prompt: null, doImport: false,
  });
  const [importStatus, setImportStatus] = useState<ImportStatus>("idle");
  const [importError, setImportError] = useState<string | null>(null);
  const importManifestRef = useRef<unknown>(null);
  const bootstrappedRef = useRef(false);
  const { setTheme, setMode } = useTheme();

  // Read embed args from the URL once on mount (client-only static export).
  useEffect(() => {
    setEmbed(readEmbedParams());
  }, []);

  useEffect(() => {
    // Load runtime config (resolves API URL from /config.json if present)
    loadRuntimeConfig().then(() => {
    setConfigReady(true);
    // Load use-cases
    listUseCases()
      .then((ucs) => {
        setUseCases(ucs);
        if (ucs.length > 0 && !ucs.find((uc) => uc.name === selectedUseCase)) {
          setSelectedUseCase(ucs[0].name);
        }
      })
      .catch(() => {
        setUseCases([{ name: "generic", displayName: "Generic Assistant", description: "", skillCount: 0, sampleQuestions: [] }]);
      });

    // Load existing conversations from Cosmos so the sidebar persists across reloads
    listConversations()
      .then((data) => {
        const convs = (data.conversations as Conversation[]) || [];
        setConversations(convs);
      })
      .catch(() => {
        // Non-fatal — sidebar will just be empty on this load
      });
    }); // end loadRuntimeConfig
  }, []);

  // Fetch skills whenever the selected use-case changes (only after config is loaded)
  useEffect(() => {
    if (!configReady) return;
    listSkills(selectedUseCase)
      .then((s) => setSkills(s))
      .catch(() => setSkills([]));
  }, [selectedUseCase, configReady]);

  const handleNewConversation = () => {
    // Navigate to the landing page for the current use case
    setActiveConversation(null);
    setPendingMessage(null);
    setSidebarOpen(false);
    setSkillsOpen(false);
  };

  // Create a conversation and optionally pre-fill a message
  const startConversation = async (message?: string, useCaseOverride?: string) => {
    const useCase = useCaseOverride ?? selectedUseCase;
    const tempId = crypto.randomUUID();
    const optimistic: Conversation = {
      id: tempId,
      title: "New Conversation",
      useCase,
      status: "active",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    setConversations((prev) => [optimistic, ...prev]);
    setActiveConversation(optimistic);
    setLandingInput("");

    try {
      const saved = await createConversation("New Conversation", useCase) as Conversation;
      const real = { ...optimistic, id: saved.id };
      setConversations((prev) =>
        prev.map((c) => (c.id === tempId ? real : c))
      );
      setActiveConversation(real);
      if (message) setPendingMessage(message);
    } catch {
      if (message) setPendingMessage(message);
    }
  };

  const handleDeleteConversation = async (conv: Conversation) => {
    // Optimistically remove from UI
    setConversations((prev) => prev.filter((c) => c.id !== conv.id));
    if (activeConversation?.id === conv.id) {
      setActiveConversation(null);
    }
    try {
      await deleteConversation(conv.id);
    } catch {
      // Restore on failure
      setConversations((prev) => [conv, ...prev]);
    }
  };

  const handleTitleChange = (conversationId: string, title: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === conversationId ? { ...c, title } : c))
    );
    setActiveConversation((prev) =>
      prev?.id === conversationId ? { ...prev, title } : prev
    );
  };

  const handleSelectConversation = (conv: Conversation) => {
    setActiveConversation(conv);
    setSelectedUseCase(conv.useCase || "generic");
    setPendingMessage(null);
    setSidebarOpen(false);
  };

  const handleSampleQuestion = async (question: string) => {
    await startConversation(question);
  };

  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  // Run the relayed manifest import (separated so the error UI can retry it).
  const runImport = useCallback(async () => {
    const manifest = importManifestRef.current;
    if (!manifest) {
      setImportStatus("error");
      setImportError("No persona manifest was found to import. Please start again from the host.");
      return;
    }
    setImportStatus("importing");
    setImportError(null);
    const promptText = readEmbedParams().prompt;
    try {
      const result = await importPersona(manifest);
      // Make the freshly-imported persona selectable and refresh the catalog.
      setUseCases((prev) =>
        prev.find((uc) => uc.name === result.name)
          ? prev
          : [...prev, {
              name: result.name,
              displayName: result.displayName,
              description: result.description,
              skillCount: result.skillCount,
              sampleQuestions: [],
            }],
      );
      listUseCases().then(setUseCases).catch(() => {});
      setSelectedUseCase(result.name);
      settlePersonaUrl(result.name);
      setImportStatus("done");
      if (promptText) {
        startConversation(promptText, result.name);
      }
    } catch (err) {
      setImportStatus("error");
      setImportError(err instanceof Error ? err.message : "Import failed. Please try again.");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Embed bootstrap: apply theme, then import / open persona / auto-prompt.
  // Runs once after runtime config + use-cases are ready.
  useEffect(() => {
    if (!configReady || bootstrappedRef.current) return;
    const params = readEmbedParams();
    if (!params.embed) return;
    bootstrappedRef.current = true;

    // Sync theme: accept a light/dark mode or a named Kratos theme, plus an
    // optional explicit &mode= so the host can pass a named theme AND a mode
    // together (e.g. &theme=agentic-loop&mode=dark for a branded dark match).
    if (params.theme) {
      if (params.theme === "light" || params.theme === "dark") {
        setMode(params.theme as Mode);
      } else if (THEME_NAMES.has(params.theme as ThemeName)) {
        setTheme(params.theme as ThemeName);
      }
    }
    if (params.mode === "light" || params.mode === "dark") {
      setMode(params.mode as Mode);
    }

    if (params.doImport) {
      importManifestRef.current = takeImportManifest();
      runImport();
      return;
    }
    if (params.persona) {
      setSelectedUseCase(params.persona);
      if (params.prompt) startConversation(params.prompt, params.persona);
      return;
    }
    if (params.prompt) {
      startConversation(params.prompt);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configReady, runImport, setMode, setTheme]);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Skip to content link for accessibility */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:px-4 focus:py-2 focus:bg-accent focus:text-accent-fg focus:rounded-lg focus:text-sm focus:font-medium focus:shadow-lg"
      >
        Skip to content
      </a>

      {/* Mobile sidebar overlay */}
      {!embed.embed && sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 lg:hidden animate-fade-in"
          onClick={closeSidebar}
        />
      )}

      {/* Sidebar — hidden in embed mode (chromeless hosting) */}
      {!embed.embed && (
      <div className={`
        fixed inset-y-0 left-0 z-50 w-[300px] transform transition-transform duration-300 ease-out
        lg:relative lg:translate-x-0 lg:z-auto
        ${sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"}
      `}>
        <Sidebar
          conversations={conversations}
          activeId={activeConversation?.id ?? null}
          onNew={handleNewConversation}
          onSelect={handleSelectConversation}
          onDelete={handleDeleteConversation}
          onOpenSettings={() => { setSettingsOpen(true); setSidebarOpen(false); }}
          onOpenSkills={() => { setSkillsOpen(true); setSidebarOpen(false); setPendingMessage(null); }}
          onOpenAgenticLoop={() => { setAgenticLoopOpen(true); setSidebarOpen(false); }}
          useCases={useCases}
          selectedUseCase={selectedUseCase}
          onSelectUseCase={setSelectedUseCase}
          onCloseMobile={closeSidebar}
        />
      </div>
      )}

      {/* Settings modal */}
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* Agentic Loop modal */}
      <AgentLoop open={agenticLoopOpen} onClose={() => setAgenticLoopOpen(false)} />

      {/* Main chat area */}
      <main id="main-content" className="flex-1 flex flex-col min-w-0">
        {activeConversation ? (
          <ChatWindow
            key={activeConversation.id}
            conversation={activeConversation}
            onTitleChange={handleTitleChange}
            initialMessage={pendingMessage ?? undefined}
            onOpenSidebar={() => setSidebarOpen(true)}
          />
        ) : (
          <div className="flex-1 flex flex-col">
            {/* Mobile top bar — hidden in embed mode (no sidebar to open) */}
            {!embed.embed && (
            <div className="lg:hidden flex items-center px-4 py-3 border-b border-border-soft bg-surface backdrop-blur">
              <button
                onClick={() => setSidebarOpen(true)}
                className="p-2 -ml-1 text-muted hover:text-text rounded-lg hover:bg-hover transition-all"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
                </svg>
              </button>
              <span className="ml-2 text-sm font-semibold text-text">Kratos Agent</span>
            </div>
            )}

            {/* Landing page */}
            <div className="flex-1 flex flex-col items-center justify-center px-4 py-8">
              <div className="w-full max-w-2xl animate-fade-in">
                {/* Hero */}
                <div className="text-center mb-10">
                  <div className="relative mx-auto mb-6 w-20 h-20">
                    <div className="absolute inset-0 rounded-2xl bg-accent blur-2xl opacity-30 animate-glow-pulse" />
                    <div className="absolute inset-[-4px] rounded-[18px] bg-accent animate-float" />
                    <div className="relative w-20 h-20 rounded-2xl bg-accent flex items-center justify-center shadow-xl ring-1 ring-white/20 animate-float">
                      <svg className="w-10 h-10 text-accent-fg drop-shadow-lg" viewBox="0 0 24 24" fill="currentColor">
                        <path fillRule="evenodd" d="M14.615 1.595a.75.75 0 01.359.852L12.982 9.75h7.268a.75.75 0 01.548 1.262l-10.5 11.25a.75.75 0 01-1.272-.71l1.992-7.302H3.75a.75.75 0 01-.548-1.262l10.5-11.25a.75.75 0 01.913-.143z" clipRule="evenodd" />
                      </svg>
                    </div>
                  </div>

                  <h1 className="text-3xl sm:text-4xl font-bold mb-3 tracking-tight">
                    <span className="gradient-text">
                      {useCases.find((uc) => uc.name === selectedUseCase)?.displayName || "Kratos Agent"}
                    </span>
                  </h1>
                  <p className="text-muted text-sm sm:text-base leading-relaxed max-w-lg mx-auto">
                    {useCases.find((uc) => uc.name === selectedUseCase)?.description || (
                      <>Enterprise AI Agent powered by GitHub Copilot SDK &amp; Microsoft Foundry</>
                    )}
                  </p>
                </div>

                {/* Chat input bar */}
                <div className="relative mb-8">
                  <div className="flex items-end gap-2 p-2 bg-surface border border-border-soft rounded-2xl shadow-lg focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--accent-soft),0_8px_32px_rgba(0,0,0,0.06)] transition-all duration-300">
                    <textarea
                      ref={landingInputRef}
                      value={landingInput}
                      onChange={(e) => {
                        setLandingInput(e.target.value);
                        // Auto-resize
                        e.target.style.height = "auto";
                        e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          if (landingInput.trim()) startConversation(landingInput.trim());
                        }
                      }}
                      placeholder="Ask me anything..."
                      rows={1}
                      className="flex-1 px-4 py-3 text-sm text-text bg-transparent resize-none focus:outline-none placeholder:text-muted leading-relaxed"
                      style={{ minHeight: "44px", maxHeight: "120px" }}
                    />
                    <button
                      onClick={() => { if (landingInput.trim()) startConversation(landingInput.trim()); }}
                      disabled={!landingInput.trim()}
                      aria-label="Send message"
                      className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-xl bg-accent text-accent-fg disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-200 shadow-md hover:shadow-lg active:scale-95"
                    >
                      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
                      </svg>
                    </button>
                  </div>
                  <p className="text-[11px] text-muted text-center mt-2">
                    <kbd className="px-1.5 py-0.5 bg-surface-2 rounded text-[10px] font-mono border border-border-soft">Enter</kbd> to send · <kbd className="px-1.5 py-0.5 bg-surface-2 rounded text-[10px] font-mono border border-border-soft">Shift+Enter</kbd> new line
                  </p>
                </div>

                {/* Sample questions */}
                {(useCases.find((uc) => uc.name === selectedUseCase)?.sampleQuestions ?? []).length > 0 && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-8 stagger-children">
                    {useCases.find((uc) => uc.name === selectedUseCase)!.sampleQuestions.map((q, i) => (
                      <button
                        key={i}
                        onClick={() => handleSampleQuestion(q)}
                        className="group text-left px-4 py-3.5 rounded-xl border border-border-soft bg-surface hover:border-accent hover:bg-hover transition-all duration-300 hover:shadow-md animate-slide-up-stagger active:scale-[0.98] backdrop-blur-sm"
                      >
                        <div className="flex items-start gap-3">
                          <div className="w-7 h-7 rounded-lg bg-accent-soft flex items-center justify-center flex-shrink-0 group-hover:bg-accent-soft transition-colors">
                            <svg className="w-3.5 h-3.5 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
                            </svg>
                          </div>
                          <span className="text-sm text-text group-hover:text-text-strong transition-colors leading-snug">{q}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                {/* Skill pills */}
                {skills.filter((s) => s.enabled).length > 0 && (
                  <div className="flex flex-wrap justify-center gap-2 px-4 animate-fade-in">
                    {skills.filter((s) => s.enabled).map((s) => (
                      <span key={s.name} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium text-muted bg-surface rounded-full border border-border-soft hover:border-accent hover:text-accent transition-all duration-200 cursor-default backdrop-blur-sm">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 dark:bg-emerald-500 animate-pulse-slow" />
                        {s.name.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Persona-import overlay (embed Variant B): shows while the relayed
          manifest is being imported, with an inline retry on failure. */}
      {embed.embed && (importStatus === "importing" || importStatus === "error") && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-bg/80 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-sm mx-4 p-6 rounded-2xl border border-border-soft bg-surface shadow-xl text-center">
            {importStatus === "importing" ? (
              <>
                <div className="mx-auto mb-4 w-10 h-10 rounded-full border-2 border-accent border-t-transparent animate-spin" />
                <h2 className="text-base font-semibold text-text mb-1">Creating your persona…</h2>
                <p className="text-sm text-muted">Importing the agent definition into Kratos.</p>
              </>
            ) : (
              <>
                <div className="mx-auto mb-4 w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center">
                  <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m0 3.75h.008M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <h2 className="text-base font-semibold text-text mb-1">Couldn&apos;t create the persona</h2>
                <p className="text-sm text-muted mb-4 break-words">{importError}</p>
                <button
                  onClick={runImport}
                  className="px-4 py-2 rounded-xl bg-accent text-accent-fg text-sm font-medium shadow-md hover:shadow-lg active:scale-95 transition-all"
                >
                  Try again
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Full-screen Agent Manager overlay — rendered on top so the active
          ChatWindow stays mounted and any in-flight stream keeps running. */}
      {skillsOpen && (
        <div className="fixed inset-0 z-[60]">
          <SkillsAdminPanel
            onClose={() => setSkillsOpen(false)}
            useCase={selectedUseCase}
            useCases={useCases}
            onSelectUseCase={setSelectedUseCase}
          />
        </div>
      )}
    </div>
  );
}
