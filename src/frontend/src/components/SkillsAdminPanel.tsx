"use client";

import { useState, useEffect, useRef } from "react";
import { listSkills, createSkill, updateSkill, deleteSkill, getSystemPrompt, updateSystemPrompt, resetSystemPrompt, listSkillFiles, upsertSkillFile, deleteSkillFile, getMCPConfig, updateMCPConfig, analyzeConsistency, applyAnalysisFix, exportUseCase } from "@/lib/api";
import type { AnalysisResult, AnalysisIssue, ApplyFixResult, MCPConfig, Skill, SkillFile, UseCase } from "@/types";
import { useTheme } from "./ThemeProvider";
import { ApmAdminPanel } from "./ApmAdminPanel";
import { EvalsAdminPanel } from "./EvalsAdminPanel";
import { TracesAdminPanel } from "./TracesAdminPanel";
import { SourceBadge } from "./SourceBadge";

type Tab = "skills" | "prompt" | "mcp" | "consistency" | "apm" | "evals" | "traces" | "deploy";

interface Props {
  onClose: () => void;
  useCase?: string;
  useCases?: UseCase[];
  onSelectUseCase?: (name: string) => void;
}

export function SkillsAdminPanel({ onClose, useCase = "generic", useCases = [], onSelectUseCase }: Props) {
  const [tab, setTab] = useState<Tab>("skills");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [editingSkill, setEditingSkill] = useState<Skill | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { mode, toggleMode } = useTheme();

  // New skill form state
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newInstructions, setNewInstructions] = useState("");

  // System prompt state
  const [promptContent, setPromptContent] = useState("");
  const [promptDraft, setPromptDraft] = useState("");
  const [promptIsDefault, setPromptIsDefault] = useState(true);
  const [promptDirty, setPromptDirty] = useState(false);
  const [promptLoading, setPromptLoading] = useState(false);

  // MCP servers state
  const [mcpServers, setMcpServers] = useState<Record<string, MCPConfig["servers"][string]>>({});
  const [mcpSources, setMcpSources] = useState<Record<string, string>>({});
  const [mcpLoading, setMcpLoading] = useState(false);
  const [mcpError, setMcpError] = useState("");
  const [editingMcp, setEditingMcp] = useState<{ name: string; config: MCPConfig["servers"][string] } | null>(null);
  const [showMcpCreate, setShowMcpCreate] = useState(false);

  // MCP create/edit form state
  const [mcpName, setMcpName] = useState("");
  const [mcpType, setMcpType] = useState<"local" | "http" | "sse">("local");
  const [mcpCommand, setMcpCommand] = useState("");
  const [mcpArgs, setMcpArgs] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpTools, setMcpTools] = useState("*");
  const [mcpEnv, setMcpEnv] = useState("");
  const [mcpCwd, setMcpCwd] = useState("");
  const [mcpHeaders, setMcpHeaders] = useState("");
  const [mcpTimeout, setMcpTimeout] = useState("");

  // Skill files state
  const [skillFiles, setSkillFiles] = useState<SkillFile[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [expandedFile, setExpandedFile] = useState<string | null>(null);
  const [showUploadForm, setShowUploadForm] = useState(false);
  const [uploadPath, setUploadPath] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Deploy / export state
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null);

  // Consistency analysis state
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [includeDisabled, setIncludeDisabled] = useState(true);
  const [expandedIssue, setExpandedIssue] = useState<number | null>(null);
  const [issueFilter, setIssueFilter] = useState<"all" | "critical" | "warning" | "info">("all");
  const [fixingIssue, setFixingIssue] = useState<number | null>(null);
  const [fixResults, setFixResults] = useState<Record<number, ApplyFixResult>>({});

  const loadSkills = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listSkills(useCase);
      setSkills(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load skills");
    } finally {
      setLoading(false);
    }
  };

  const loadPrompt = async () => {
    setPromptLoading(true);
    setError("");
    try {
      const data = await getSystemPrompt(useCase);
      setPromptContent(data.content);
      setPromptDraft(data.content);
      setPromptIsDefault(data.isDefault);
      setPromptDirty(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load system prompt");
    } finally {
      setPromptLoading(false);
    }
  };

  const loadMCPConfig = async () => {
    setMcpLoading(true);
    setMcpError("");
    try {
      const data = await getMCPConfig(useCase);
      setMcpServers(data.servers);
      setMcpSources(data.sources ?? {});
    } catch (err) {
      setMcpError(err instanceof Error ? err.message : "Failed to load MCP config");
    } finally {
      setMcpLoading(false);
    }
  };

  const resetMcpForm = () => {
    setMcpName(""); setMcpType("local"); setMcpCommand(""); setMcpArgs(""); setMcpUrl("");
    setMcpTools("*"); setMcpEnv(""); setMcpCwd(""); setMcpHeaders(""); setMcpTimeout("");
  };

  const populateMcpForm = (name: string, cfg: MCPConfig["servers"][string]) => {
    setMcpName(name);
    // Backward compat: old configs may have type "remote" — map to "http"
    const t = cfg.type === ("remote" as string) ? "http" : cfg.type;
    setMcpType(t as "local" | "http" | "sse");
    setMcpTools((cfg.tools ?? ["*"]).join(", "));
    if (cfg.type === "local") {
      setMcpCommand(cfg.command);
      setMcpArgs((cfg.args ?? []).join(", "));
      setMcpEnv(cfg.env ? Object.entries(cfg.env).map(([k,v]) => `${k}=${v}`).join("\n") : "");
      setMcpCwd(cfg.cwd ?? "");
      setMcpUrl(""); setMcpHeaders(""); setMcpTimeout("");
    } else {
      setMcpUrl(cfg.url);
      setMcpHeaders(cfg.headers ? Object.entries(cfg.headers).map(([k,v]) => `${k}: ${v}`).join("\n") : "");
      setMcpTimeout(cfg.timeout != null ? String(cfg.timeout) : "");
      setMcpCommand(""); setMcpArgs(""); setMcpEnv(""); setMcpCwd("");
    }
  };

  const buildMcpConfig = (): MCPConfig["servers"][string] => {
    const tools = mcpTools.split(",").map(t => t.trim()).filter(Boolean);
    if (mcpType === "local") {
      const env: Record<string, string> = {};
      mcpEnv.split("\n").forEach(line => { const [k, ...v] = line.split("="); if (k?.trim()) env[k.trim()] = v.join("=").trim(); });
      return {
        type: "local" as const, command: mcpCommand,
        args: mcpArgs ? mcpArgs.split(",").map(a => a.trim()).filter(Boolean) : [],
        tools,
        ...(Object.keys(env).length ? { env } : {}),
        ...(mcpCwd.trim() ? { cwd: mcpCwd.trim() } : {}),
      };
    } else {
      const headers: Record<string, string> = {};
      mcpHeaders.split("\n").forEach(line => { const idx = line.indexOf(":"); if (idx > 0) headers[line.slice(0, idx).trim()] = line.slice(idx + 1).trim(); });
      return {
        type: mcpType as "http" | "sse", url: mcpUrl, tools,
        ...(Object.keys(headers).length ? { headers } : {}),
        ...(mcpTimeout.trim() ? { timeout: Number(mcpTimeout) } : {}),
      };
    }
  };

  const handleSaveMcpServer = async () => {
    setMcpError("");
    const name = mcpName.trim();
    if (!name) { setMcpError("Server name is required."); return; }
    if (mcpType === "local" && !mcpCommand.trim()) { setMcpError("Command is required for local servers."); return; }
    if ((mcpType === "http" || mcpType === "sse") && !mcpUrl.trim()) { setMcpError("URL is required for remote servers."); return; }
    const updated = { ...mcpServers, [name]: buildMcpConfig() };
    try {
      const data = await updateMCPConfig(useCase, updated);
      setMcpServers(data.servers);
      setMcpSources(data.sources ?? {});
      setEditingMcp(null);
      setShowMcpCreate(false);
      resetMcpForm();
    } catch (err) {
      setMcpError(err instanceof Error ? err.message : "Failed to save MCP server");
    }
  };

  const handleDeleteMcp = async (name: string) => {
    if (!confirm(`Delete MCP server "${name}"? This cannot be undone.`)) return;
    setMcpError("");
    const updated = { ...mcpServers };
    delete updated[name];
    try {
      const data = await updateMCPConfig(useCase, updated);
      setMcpServers(data.servers);
      setMcpSources(data.sources ?? {});
    } catch (err) {
      setMcpError(err instanceof Error ? err.message : "Failed to delete MCP server");
    }
  };

  useEffect(() => {
    loadSkills();
    loadPrompt();
    loadMCPConfig();
  }, [useCase]);

  const handleToggle = async (skill: Skill) => {
    try {
      const updated = await updateSkill(skill.name, { enabled: !skill.enabled }, useCase);
      setSkills((prev) => prev.map((s) => (s.name === updated.name ? updated : s)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update skill");
    }
  };

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setError("");
    try {
      const created = await createSkill({
        name: newName.trim().toLowerCase().replace(/\s+/g, "-"),
        description: newDescription,
        enabled: true,
        instructions: newInstructions,
      }, useCase);
      setSkills((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
      setShowCreate(false);
      setNewName("");
      setNewDescription("");
      setNewInstructions("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create skill");
    }
  };

  const handleSaveEdit = async () => {
    if (!editingSkill) return;
    setError("");
    try {
      const updated = await updateSkill(editingSkill.name, {
        description: editingSkill.description,
        instructions: editingSkill.instructions,
      }, useCase);
      setSkills((prev) => prev.map((s) => (s.name === updated.name ? updated : s)));
      setEditingSkill(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save skill");
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete skill "${name}"? This cannot be undone.`)) return;
    setError("");
    try {
      await deleteSkill(name, useCase);
      setSkills((prev) => prev.filter((s) => s.name !== name));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete skill");
    }
  };

  const handleSavePrompt = async () => {
    setError("");
    try {
      const data = await updateSystemPrompt(promptDraft, useCase);
      setPromptContent(data.content);
      setPromptIsDefault(data.isDefault);
      setPromptDirty(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save system prompt");
    }
  };

  const handleResetPrompt = async () => {
    if (!confirm("Reset to the default system prompt? Your custom prompt will be deleted.")) return;
    setError("");
    try {
      await resetSystemPrompt(useCase);
      await loadPrompt();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset system prompt");
    }
  };

  // ─── File management ───────────────────────────────────────────────────

  useEffect(() => {
    if (editingSkill) {
      setSkillFiles([]);
      setExpandedFile(null);
      setShowUploadForm(false);
      setUploadPath("");
      setFilesLoading(true);
      listSkillFiles(editingSkill.name, useCase)
        .then((d) => setSkillFiles(d.files))
        .catch(() => setSkillFiles([]))
        .finally(() => setFilesLoading(false));
    } else {
      setSkillFiles([]);
      setExpandedFile(null);
    }
  }, [editingSkill?.name]);

  const handleUploadFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!editingSkill || !e.target.files?.[0]) return;
    const file = e.target.files[0];
    setError("");
    try {
      const content = await file.text();
      // Build final path: strip trailing slash from prefix, join with filename
      const prefix = uploadPath.trim().replace(/\/+$/, "");
      const filePath = prefix ? `${prefix}/${file.name}` : file.name;
      await upsertSkillFile(editingSkill.name, filePath, content, useCase);
      const existing = skillFiles.findIndex((f) => f.path === filePath);
      const updated: SkillFile = { path: filePath, name: file.name, content };
      setSkillFiles((prev) =>
        existing >= 0
          ? prev.map((f) => (f.path === filePath ? updated : f))
          : [...prev, updated]
      );
      // Refresh skill list so fileCount badge updates
      setSkills((prev) =>
        prev.map((s) =>
          s.name === editingSkill.name
            ? { ...s, fileCount: (s.fileCount ?? 0) + (existing >= 0 ? 0 : 1) }
            : s
        )
      );
      setShowUploadForm(false);
      setUploadPath("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload file");
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDeleteFile = async (filePath: string) => {
    if (!editingSkill) return;
    if (!confirm(`Delete file "${filePath}"? This cannot be undone.`)) return;
    setError("");
    try {
      await deleteSkillFile(editingSkill.name, filePath, useCase);
      setSkillFiles((prev) => prev.filter((f) => f.path !== filePath));
      if (expandedFile === filePath) setExpandedFile(null);
      setSkills((prev) =>
        prev.map((s) =>
          s.name === editingSkill.name
            ? { ...s, fileCount: Math.max(0, (s.fileCount ?? 0) - 1) }
            : s
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete file");
    }
  };

  const handleRunAnalysis = async () => {
    setAnalysisLoading(true);
    setError("");
    setAnalysisResult(null);
    setExpandedIssue(null);
    setFixResults({});
    try {
      const result = await analyzeConsistency(useCase, includeDisabled);
      setAnalysisResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setAnalysisLoading(false);
    }
  };

  const handleApplyFix = async (issue: AnalysisIssue, issueIdx: number) => {
    setFixingIssue(issueIdx);
    try {
      const result = await applyAnalysisFix(issue, useCase);
      setFixResults((prev) => ({ ...prev, [issueIdx]: result }));
      if (result.success) {
        // Refresh skills list since a skill may have been modified/disabled
        loadSkills();
      }
    } catch (err) {
      setFixResults((prev) => ({
        ...prev,
        [issueIdx]: { success: false, changes: [], error: err instanceof Error ? err.message : "Failed to apply fix" },
      }));
    } finally {
      setFixingIssue(null);
    }
  };

  const currentUseCaseMeta = useCases.find((uc) => uc.name === useCase);
  const currentDisplayName = currentUseCaseMeta?.displayName ?? useCase;

  const handleExport = async () => {
    if (!useCase || exporting) return;
    setExporting(true);
    setExportError(null);
    try {
      const blob = await exportUseCase(useCase);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${useCase}-foundry-agent.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  const copyCmd = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedCmd(id);
      setTimeout(() => setCopiedCmd((cur) => (cur === id ? null : cur)), 1500);
    } catch {
      // Clipboard unavailable (insecure context) — silently no-op.
    }
  };

  const navItems: { id: Tab; label: string; icon: string }[] = [
    { id: "skills", label: "Skills", icon: "puzzle" },
    { id: "prompt", label: "System Prompt", icon: "document" },
    { id: "mcp", label: "MCP Servers", icon: "server" },
    { id: "apm", label: "APM", icon: "package" },
    { id: "consistency", label: "Consistency", icon: "shield" },
    { id: "evals", label: "Evals", icon: "chart" },
    { id: "traces", label: "Traces", icon: "activity" },
    { id: "deploy", label: "Deploy", icon: "rocket" },
  ];

  const renderNavIcon = (icon: string) => {
    switch (icon) {
      case "puzzle": return <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M14.25 6.087c0-.355.186-.676.401-.959.221-.29.349-.634.349-1.003 0-1.036-1.007-1.875-2.25-1.875s-2.25.84-2.25 1.875c0 .369.128.713.349 1.003.215.283.401.604.401.959v0a.64.64 0 01-.657.643 48.39 48.39 0 01-4.163-.3c.186 1.613.166 3.532-1.005 3.532a1.5 1.5 0 01-1.5-1.5v0c0-.828-.895-1.5-2-1.5s-2 .672-2 1.5v0a1.5 1.5 0 01-1.5 1.5c-1.171 0-1.191-1.919-1.005-3.532a48.39 48.39 0 01-4.163.3A.64.64 0 012.25 6.73v0c0-.355.186-.676.401-.959.221-.29.349-.634.349-1.003C3 3.732 3.84 2.875 5.25 2.875s2.25.857 2.25 1.893c0 .369-.128.713-.349 1.003" /></svg>;
      case "document": return <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" /></svg>;
      case "server": return <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" /></svg>;
      case "shield": return <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" /></svg>;
      case "package": return <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9" /></svg>;
      case "chart": return <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" /></svg>;
      case "activity": return <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3.75 12h2.25l2.25-6 3 12 3-9 2.25 3h3.75" /></svg>;
      case "rocket": return <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M15.59 14.37a6 6 0 01-5.84 7.38v-4.8m5.84-2.58a14.98 14.98 0 006.16-12.12A14.98 14.98 0 009.631 8.41m5.96 5.96a14.926 14.926 0 01-5.841 2.58m-.119-8.54a6 6 0 00-7.381 5.84h4.8m2.581-5.84a14.927 14.927 0 00-2.58 5.84m2.699 2.7c-.103.021-.207.041-.311.06a15.09 15.09 0 01-2.448-2.448 14.9 14.9 0 01.06-.312m-2.24 2.39a4.493 4.493 0 00-1.757 4.306 4.493 4.493 0 004.306-1.758M16.5 9a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z" /></svg>;
      default: return null;
    }
  };

  return (
    <div className="flex h-screen bg-bg">
      {/* Mobile nav overlay */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 md:hidden animate-fade-in"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      {/* Left sidebar navigation */}
      <aside className={`
        fixed inset-y-0 left-0 z-50 w-[280px] bg-surface-2 border-r border-border-soft flex flex-col
        transform transition-transform duration-300 ease-out
        md:relative md:translate-x-0 md:z-auto
        ${mobileNavOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}
      `}>
        {/* Header */}
        <div className="px-5 py-4">
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="w-9 h-9 rounded-xl bg-hover hover:bg-hover border border-border-soft flex items-center justify-center transition-all flex-shrink-0"
              title="Back to Chat"
            >
              <svg className="w-4 h-4 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
              </svg>
            </button>
            <div className="flex-1 min-w-0">
              <h1 className="font-semibold text-text-strong text-sm tracking-tight">Agent Manager</h1>
              <p className="text-[11px] text-muted">Configure skills, prompts &amp; MCP</p>
            </div>
            {/* Mobile close */}
            <button
              onClick={() => setMobileNavOpen(false)}
              className="md:hidden p-1.5 text-muted hover:text-text-strong rounded-lg hover:bg-hover transition-all"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Use case selector */}
        {useCases.length > 1 && (
          <div className="px-4 pb-3">
            <label className="block text-[10px] font-semibold text-muted uppercase tracking-wider mb-1.5 px-1">
              Agent Persona
            </label>
            <div className="relative">
              <select
                value={useCase}
                onChange={(e) => onSelectUseCase?.(e.target.value)}
                className="w-full text-sm text-text-strong bg-hover border border-border-soft rounded-lg pl-3 pr-9 py-2.5 focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent appearance-none cursor-pointer hover:bg-hover hover:border-border transition-all"
              >
                {useCases.map((uc) => (
                  <option key={uc.name} value={uc.name} className="bg-surface-2">
                    {uc.displayName} ({uc.skillCount} skills)
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5">
                <svg className="w-4 h-4 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
                </svg>
              </div>
            </div>
          </div>
        )}

        <div className="mx-4 my-1 border-t border-border-soft" />

        {/* Navigation items */}
        <nav className="flex-1 px-3 py-2 space-y-1">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => { setTab(item.id); setMobileNavOpen(false); setEditingSkill(null); setShowCreate(false); setEditingMcp(null); setShowMcpCreate(false); }}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-150 ${
                tab === item.id
                  ? "bg-hover text-text-strong font-medium"
                  : "text-muted hover:text-text-strong hover:bg-hover"
              }`}
            >
              <span className={tab === item.id ? "text-accent" : "text-muted"}>
                {renderNavIcon(item.icon)}
              </span>
              {item.label}
              {item.id === "skills" && skills.length > 0 && (
                <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded-full bg-hover text-muted font-mono">
                  {skills.length}
                </span>
              )}
              {item.id === "mcp" && Object.keys(mcpServers).length > 0 && (
                <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded-full bg-hover text-muted font-mono">
                  {Object.keys(mcpServers).length}
                </span>
              )}
              {item.id === "consistency" && analysisResult && (
                <span className={`ml-auto text-[10px] px-1.5 py-0.5 rounded-full font-mono ${
                  analysisResult.overallScore >= 90 ? "bg-emerald-500/20 text-emerald-400" :
                  analysisResult.overallScore >= 70 ? "bg-blue-500/20 text-blue-400" :
                  analysisResult.overallScore >= 50 ? "bg-amber-500/20 text-amber-400" :
                  "bg-red-500/20 text-red-400"
                }`}>
                  {analysisResult.overallScore}
                </span>
              )}
            </button>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-3 py-3 border-t border-border-soft">
          <button
            onClick={onClose}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 text-sm text-text-strong hover:text-text-strong hover:bg-hover rounded-xl transition-all duration-150"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
            </svg>
            Back to Chat
          </button>
          <div className="pt-2 px-3 flex items-center justify-between">
            <p className="text-[10px] text-muted flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-slow"></span>
              {useCase.replace(/-/g, " ")}
            </p>
            <button
              onClick={toggleMode}
              className="p-1.5 text-muted hover:text-text-strong rounded-lg hover:bg-hover transition-all"
              title={mode === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            >
              {mode === "dark" ? (
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
      </aside>

      {/* Main content area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top bar */}
        <header className="border-b border-border-soft px-4 sm:px-8 py-4 bg-surface backdrop-blur">
          <div className="flex items-center gap-3">
            {/* Mobile hamburger */}
            <button
              onClick={() => setMobileNavOpen(true)}
              className="md:hidden p-2 -ml-1 text-muted hover:text-text rounded-lg hover:bg-hover transition-all"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              </svg>
            </button>
            <div className="flex-1 min-w-0">
              <h2 className="text-lg font-semibold text-text">
                {tab === "skills" ? (showCreate ? "Create Skill" : "Skills") : tab === "prompt" ? "System Prompt" : tab === "consistency" ? "Consistency Analysis" : tab === "apm" ? "APM Packages" : tab === "evals" ? "Evaluations" : tab === "traces" ? "Traces" : tab === "deploy" ? "Deploy as Foundry Agent" : (editingMcp ? `Edit: ${editingMcp.name}` : showMcpCreate ? "Add MCP Server" : "MCP Servers")}
              </h2>
              <p className="text-xs text-muted mt-0.5">
                {tab === "skills" ? `${skills.filter(s => s.enabled).length} of ${skills.length} active` : tab === "prompt" ? "Configure the system prompt for all conversations" : tab === "consistency" ? "Detect contradictions, overlaps, and gaps in your agent configuration" : tab === "apm" ? "Manage Agent Package Manager dependencies for this use-case" : tab === "evals" ? "Validate agent behavior with automated eval scenarios" : tab === "traces" ? "App Insights waterfall view for recent operations" : tab === "deploy" ? "Package this persona as a standalone Microsoft Foundry Hosted Agent" : `${Object.keys(mcpServers).length} server${Object.keys(mcpServers).length !== 1 ? "s" : ""} configured`}
              </p>
            </div>
            {/* Action buttons */}
            {tab === "skills" && !showCreate && (
              <button
                onClick={() => setShowCreate(true)}
                className="flex items-center gap-2 px-4 py-2 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                <span className="hidden sm:inline">Add Skill</span>
              </button>
            )}
            {tab === "mcp" && !editingMcp && !showMcpCreate && (
              <button
                onClick={() => { resetMcpForm(); setShowMcpCreate(true); }}
                className="flex items-center gap-2 px-4 py-2 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
                <span className="hidden sm:inline">Add Server</span>
              </button>
            )}
            {tab === "consistency" && analysisResult && !analysisLoading && (
              <button
                onClick={handleRunAnalysis}
                className="flex items-center gap-2 px-4 py-2 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182" />
                </svg>
                <span className="hidden sm:inline">Re-run</span>
              </button>
            )}
          </div>
        </header>

        {/* Error banner */}
        {error && (
          <div className="mx-4 sm:mx-8 mt-4 px-4 py-3 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 text-sm rounded-xl border border-red-100 dark:border-red-500/20 animate-fade-in flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError("")} className="text-red-400 hover:text-red-600 transition-colors">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 sm:px-8 py-6">
          {tab === "mcp" ? (
            /* ── MCP Servers tab ── */
            mcpLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="animate-spin rounded-full h-8 w-8 border-2 border-accent border-t-transparent" />
              </div>
            ) : editingMcp ? (
              /* ── MCP Edit view ── */
              <div className="max-w-3xl space-y-5">
                {mcpError && <div className="px-4 py-2.5 bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 text-sm rounded-xl border border-red-100 dark:border-red-500/20">{mcpError}</div>}
                <div>
                  <label className="block text-sm font-medium text-text mb-1.5">Type</label>
                  <select value={mcpType} onChange={(e) => setMcpType(e.target.value as "local" | "http" | "sse")} className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all">
                    <option value="local">Local (stdio)</option>
                    <option value="http">Remote (HTTP)</option>
                    <option value="sse">Remote (SSE)</option>
                  </select>
                </div>
                {mcpType === "local" ? (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Command <span className="text-red-500">*</span></label>
                      <input type="text" value={mcpCommand} onChange={(e) => setMcpCommand(e.target.value)} placeholder="faker-mcp-server" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Arguments <span className="text-muted text-xs font-normal">(comma-separated)</span></label>
                      <input type="text" value={mcpArgs} onChange={(e) => setMcpArgs(e.target.value)} placeholder="--port, 3000" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Environment Variables <span className="text-muted text-xs font-normal">(KEY=VALUE per line)</span></label>
                      <textarea value={mcpEnv} onChange={(e) => setMcpEnv(e.target.value)} rows={3} placeholder={"API_KEY=abc123\nDEBUG=true"} className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Working Directory</label>
                      <input type="text" value={mcpCwd} onChange={(e) => setMcpCwd(e.target.value)} placeholder="/path/to/dir" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">URL <span className="text-red-500">*</span></label>
                      <input type="text" value={mcpUrl} onChange={(e) => setMcpUrl(e.target.value)} placeholder="https://mcp.example.com/sse" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Headers <span className="text-muted text-xs font-normal">(Key: Value per line)</span></label>
                      <textarea value={mcpHeaders} onChange={(e) => setMcpHeaders(e.target.value)} rows={3} placeholder={"Authorization: Bearer token123\nX-Custom: value"} className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Timeout <span className="text-muted text-xs font-normal">(seconds)</span></label>
                      <input type="number" value={mcpTimeout} onChange={(e) => setMcpTimeout(e.target.value)} placeholder="30" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                  </>
                )}
                <div>
                  <label className="block text-sm font-medium text-text mb-1.5">Tools <span className="text-muted text-xs font-normal">(comma-separated, * = all)</span></label>
                  <input type="text" value={mcpTools} onChange={(e) => setMcpTools(e.target.value)} placeholder="*" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                </div>
                <div className="flex justify-end gap-3">
                  <button onClick={() => { setEditingMcp(null); resetMcpForm(); }} className="px-4 py-2 text-sm text-muted bg-surface-2 border border-border-soft rounded-xl hover:bg-hover transition-all font-medium">Cancel</button>
                  <button onClick={handleSaveMcpServer} className="px-4 py-2 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium">Save Changes</button>
                </div>
              </div>
            ) : showMcpCreate ? (
              /* ── MCP Create view ── */
              <div className="max-w-3xl space-y-5">
                {mcpError && <div className="px-3 py-2 bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 text-sm rounded-lg">{mcpError}</div>}
                <div>
                  <label className="block text-sm font-medium text-text mb-1.5">Server Name <span className="text-red-500">*</span></label>
                  <input type="text" value={mcpName} onChange={(e) => setMcpName(e.target.value)} placeholder="my-mcp-server" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-text mb-1.5">Type</label>
                  <select value={mcpType} onChange={(e) => setMcpType(e.target.value as "local" | "http" | "sse")} className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all">
                    <option value="local">Local (stdio)</option>
                    <option value="http">Remote (HTTP)</option>
                    <option value="sse">Remote (SSE)</option>
                  </select>
                </div>
                {mcpType === "local" ? (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Command <span className="text-red-500">*</span></label>
                      <input type="text" value={mcpCommand} onChange={(e) => setMcpCommand(e.target.value)} placeholder="faker-mcp-server" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Arguments <span className="text-muted text-xs font-normal">(comma-separated)</span></label>
                      <input type="text" value={mcpArgs} onChange={(e) => setMcpArgs(e.target.value)} placeholder="--port, 3000" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Environment Variables <span className="text-muted text-xs font-normal">(KEY=VALUE per line)</span></label>
                      <textarea value={mcpEnv} onChange={(e) => setMcpEnv(e.target.value)} rows={3} placeholder={"API_KEY=abc123\nDEBUG=true"} className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Working Directory</label>
                      <input type="text" value={mcpCwd} onChange={(e) => setMcpCwd(e.target.value)} placeholder="/path/to/dir" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">URL <span className="text-red-500">*</span></label>
                      <input type="text" value={mcpUrl} onChange={(e) => setMcpUrl(e.target.value)} placeholder="https://mcp.example.com/sse" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Headers <span className="text-muted text-xs font-normal">(Key: Value per line)</span></label>
                      <textarea value={mcpHeaders} onChange={(e) => setMcpHeaders(e.target.value)} rows={3} placeholder={"Authorization: Bearer token123\nX-Custom: value"} className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-text mb-1.5">Timeout <span className="text-muted text-xs font-normal">(seconds)</span></label>
                      <input type="number" value={mcpTimeout} onChange={(e) => setMcpTimeout(e.target.value)} placeholder="30" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                    </div>
                  </>
                )}
                <div>
                  <label className="block text-sm font-medium text-text mb-1.5">Tools <span className="text-muted text-xs font-normal">(comma-separated, * = all)</span></label>
                  <input type="text" value={mcpTools} onChange={(e) => setMcpTools(e.target.value)} placeholder="*" className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all" />
                </div>
                <div className="flex justify-end gap-3">
                  <button onClick={() => { setShowMcpCreate(false); resetMcpForm(); }} className="px-4 py-2 text-sm text-muted bg-surface-2 border border-border-soft rounded-xl hover:bg-hover transition-all font-medium">Cancel</button>
                  <button onClick={handleSaveMcpServer} disabled={!mcpName.trim()} className="px-4 py-2 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium disabled:opacity-50">Add Server</button>
                </div>
              </div>
            ) : (
              /* ── MCP server list ── */
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {Object.keys(mcpServers).length === 0 ? (
                  <div className="col-span-full text-center py-16">
                    <div className="w-16 h-16 mx-auto rounded-2xl bg-surface-2 flex items-center justify-center mb-4">
                      <svg className="w-8 h-8 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3" />
                      </svg>
                    </div>
                    <p className="text-sm text-muted font-medium">No MCP servers configured</p>
                    <p className="text-xs text-muted mt-1">Add a server to extend agent capabilities</p>
                  </div>
                ) : (
                  Object.entries(mcpServers).map(([name, cfg]) => (
                    <div key={name} className="flex flex-col p-5 border border-border-soft rounded-2xl bg-surface hover:border-border hover:shadow-card-hover transition-all">
                      <div className="flex items-start gap-3 mb-3">
                        <span className={`text-xs px-2.5 py-1 rounded-lg font-medium flex-shrink-0 ${
                          cfg.type === "local" ? "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/20" : "bg-blue-50 dark:bg-blue-500/10 text-blue-700 dark:text-blue-400 border border-blue-200 dark:border-blue-500/20"
                        }`}>{cfg.type.toUpperCase()}</span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-sm text-text truncate">{name}</span>
                            <SourceBadge source={mcpSources[name]} />
                          </div>
                          <p className="text-xs text-muted truncate font-mono mt-1">
                            {cfg.type === "local" ? cfg.command : cfg.url}
                          </p>
                          {cfg.tools && cfg.tools.length > 0 && cfg.tools[0] !== "*" && (
                            <p className="text-[10px] text-muted mt-1">{cfg.tools.length} tool{cfg.tools.length !== 1 ? "s" : ""} configured</p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 mt-auto pt-3 border-t border-border-soft">
                        <button onClick={() => { populateMcpForm(name, cfg); setEditingMcp({ name, config: cfg }); }} className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-text hover:text-accent hover:bg-accent-hover rounded-lg transition-all font-medium">
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
                          Edit
                        </button>
                        <button onClick={() => handleDeleteMcp(name)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-muted hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-lg transition-all font-medium">
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                          Delete
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )
          ) : tab === "prompt" ? (
            /* ── System Prompt tab ── */
            promptLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
              </div>
            ) : (
              <div className="max-w-3xl space-y-5">
                <div className="flex items-center justify-between">
                  <label className="block text-sm font-medium text-text">
                    System prompt sent to the LLM at the start of every conversation
                  </label>
                  {promptIsDefault ? (
                    <span className="text-xs bg-surface-2 dark:bg-slate-700/50 text-muted px-2 py-0.5 rounded-full">Default</span>
                  ) : (
                    <span className="text-xs bg-accent-soft text-accent px-2 py-0.5 rounded-full">Custom</span>
                  )}
                </div>
                <textarea
                  value={promptDraft}
                  onChange={(e) => {
                    setPromptDraft(e.target.value);
                    setPromptDirty(e.target.value !== promptContent);
                  }}
                  rows={20}
                  className="w-full px-4 py-3 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all resize-y"
                />
                <div className="flex justify-between">
                  <button
                    onClick={handleResetPrompt}
                    disabled={promptIsDefault}
                    className="px-4 py-2 text-sm text-muted bg-surface-2 border border-border-soft rounded-xl hover:bg-hover transition-all font-medium disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Reset to Default
                  </button>
                  <div className="flex gap-3">
                    <button
                      onClick={() => {
                        setPromptDraft(promptContent);
                        setPromptDirty(false);
                      }}
                      disabled={!promptDirty}
                      className="px-4 py-2 text-sm text-muted bg-surface-2 border border-border-soft rounded-xl hover:bg-hover transition-all font-medium disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      Discard
                    </button>
                    <button
                      onClick={handleSavePrompt}
                      disabled={!promptDirty || !promptDraft.trim()}
                      className="px-4 py-2 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Save Prompt
                    </button>
                  </div>
                </div>
                <p className="text-xs text-muted">
                  Changes take effect on the next new conversation. Existing sessions are not affected.
                </p>
              </div>
            )
          ) : tab === "apm" ? (
            /* ── APM tab ── */
            <div className="max-w-4xl">
              <ApmAdminPanel useCase={useCase} onMcpChange={loadMCPConfig} />
            </div>
          ) : tab === "evals" ? (
            /* ── Evals tab ── */
            <EvalsAdminPanel useCase={useCase} />
          ) : tab === "traces" ? (
            /* ── Traces tab ── */
            <TracesAdminPanel useCase={useCase} />
          ) : tab === "deploy" ? (
            /* ── Deploy tab ── */
            <div className="max-w-3xl space-y-6">
              {/* Hero / explainer */}
              <div className="rounded-2xl border border-border-soft bg-surface p-5 sm:p-6">
                <div className="flex items-start gap-4">
                  <div className="w-11 h-11 rounded-xl bg-accent-soft text-accent flex items-center justify-center flex-shrink-0">
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.59 14.37a6 6 0 01-5.84 7.38v-4.8m5.84-2.58a14.98 14.98 0 006.16-12.12A14.98 14.98 0 009.631 8.41m5.96 5.96a14.926 14.926 0 01-5.841 2.58m-.119-8.54a6 6 0 00-7.381 5.84h4.8m2.581-5.84a14.927 14.927 0 00-2.58 5.84m2.699 2.7c-.103.021-.207.041-.311.06a15.09 15.09 0 01-2.448-2.448 14.9 14.9 0 01.06-.312m-2.24 2.39a4.493 4.493 0 00-1.757 4.306 4.493 4.493 0 004.306-1.758M16.5 9a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-base font-semibold text-text-strong">
                      Ship <span className="text-accent">{currentDisplayName}</span> as a Foundry Hosted Agent
                    </h3>
                    <p className="mt-1 text-sm text-muted leading-relaxed">
                      Download a self-contained <code className="font-mono text-[12px] bg-hover px-1.5 py-0.5 rounded">azd</code> project that
                      deploys this persona — skills, prompt, MCP config, and infra — as a standalone
                      Microsoft Foundry Hosted Agent in any Azure subscription. Kratos is not required at runtime.
                    </p>
                  </div>
                </div>

                <div className="mt-5 flex flex-col sm:flex-row gap-3 sm:items-center">
                  <button
                    onClick={handleExport}
                    disabled={exporting || !useCase}
                    className="flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-medium text-accent-fg bg-accent hover:bg-accent-hover rounded-xl transition-all shadow-card disabled:opacity-50 disabled:cursor-wait"
                  >
                    {exporting ? (
                      <>
                        <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={3} className="opacity-25" />
                          <path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth={3} className="opacity-75" strokeLinecap="round" />
                        </svg>
                        Packing&hellip;
                      </>
                    ) : (
                      <>
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                        </svg>
                        Download {useCase}-foundry-agent.zip
                      </>
                    )}
                  </button>
                  <p className="text-[11px] text-muted">
                    Typical bundle: ~150 files, ~300 KB. Generated on demand from the live persona configuration.
                  </p>
                </div>

                {exportError && (
                  <div className="mt-3 px-3 py-2 rounded-lg bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 text-xs border border-red-100 dark:border-red-500/20">
                    {exportError}
                  </div>
                )}
              </div>

              {/* What's inside */}
              <section>
                <h4 className="text-sm font-semibold text-text-strong mb-3">What&apos;s inside the ZIP</h4>
                <ul className="space-y-2 text-sm text-text">
                  {[
                    { path: "infra/", desc: "Bicep for Foundry account, project, ACR, monitoring, and RBAC." },
                    { path: "src/hosted-agent/", desc: "MAF orchestrator container — pinned to agent-framework-core ~=1.7.0." },
                    { path: "src/backend/app/", desc: "Persona runtime: skills, system prompt, MCP config, SkillsProvider wiring." },
                    { path: "use-cases/" + useCase + "/", desc: "This persona's curated skills + assets (frozen at download time)." },
                    { path: "azure.yaml + agent.yaml", desc: "azd service map + ContainerAgent schema for the azure.ai.agents extension." },
                    { path: "README.md", desc: "Step-by-step deploy + invoke walkthrough." },
                  ].map((row) => (
                    <li key={row.path} className="flex items-start gap-3">
                      <code className="font-mono text-[12px] bg-hover text-text-strong px-2 py-0.5 rounded shrink-0">{row.path}</code>
                      <span className="text-muted">{row.desc}</span>
                    </li>
                  ))}
                </ul>
              </section>

              {/* Prerequisites */}
              <section>
                <h4 className="text-sm font-semibold text-text-strong mb-3">Prerequisites</h4>
                <ul className="space-y-1.5 text-sm text-muted list-disc pl-5">
                  <li>Azure subscription with Microsoft Foundry preview features enabled.</li>
                  <li>
                    <code className="font-mono text-[12px] bg-hover text-text px-1.5 py-0.5 rounded">azd</code> CLI ≥ 1.20
                    with the <code className="font-mono text-[12px] bg-hover text-text px-1.5 py-0.5 rounded">azure.ai.agents</code> extension.
                  </li>
                  <li>
                    <strong className="text-text">Foundry Project Manager</strong> role on the target Foundry project
                    (so the postdeploy hook can auto-assign <em>Foundry User</em> to the agent identity).
                  </li>
                  <li>
                    A supported region: <code className="font-mono text-[12px] bg-hover text-text px-1.5 py-0.5 rounded">northcentralus</code>,
                    {" "}<code className="font-mono text-[12px] bg-hover text-text px-1.5 py-0.5 rounded">eastus</code>,
                    {" "}<code className="font-mono text-[12px] bg-hover text-text px-1.5 py-0.5 rounded">swedencentral</code>,
                    or <code className="font-mono text-[12px] bg-hover text-text px-1.5 py-0.5 rounded">westus</code>.
                  </li>
                </ul>
              </section>

              {/* Deploy steps */}
              <section>
                <h4 className="text-sm font-semibold text-text-strong mb-3">Deploy</h4>
                <ol className="space-y-3">
                  {[
                    { id: "unzip", label: "Unzip + enter the project", cmd: `unzip ${useCase}-foundry-agent.zip && cd ${useCase}-foundry-agent` },
                    { id: "auth", label: "Authenticate with Azure", cmd: "azd auth login" },
                    { id: "up", label: "Provision infra + deploy the agent", cmd: `azd up -e ${useCase}-prod` },
                    { id: "invoke", label: "Smoke test the deployed agent", cmd: 'azd ai agent invoke "Hello!"' },
                  ].map((step, idx) => (
                    <li key={step.id} className="rounded-xl border border-border-soft bg-surface overflow-hidden">
                      <div className="flex items-center gap-3 px-4 py-2 border-b border-border-soft bg-surface-2">
                        <span className="w-5 h-5 rounded-full bg-accent text-accent-fg text-[11px] font-semibold flex items-center justify-center flex-shrink-0">
                          {idx + 1}
                        </span>
                        <span className="text-xs font-medium text-text flex-1">{step.label}</span>
                        <button
                          onClick={() => copyCmd(step.cmd, step.id)}
                          className="text-[11px] text-muted hover:text-text px-2 py-1 rounded hover:bg-hover transition-all"
                          aria-label={`Copy ${step.label}`}
                        >
                          {copiedCmd === step.id ? "Copied!" : "Copy"}
                        </button>
                      </div>
                      <pre className="px-4 py-2.5 text-xs font-mono text-text-strong overflow-x-auto">
                        <span className="text-muted select-none">$ </span>{step.cmd}
                      </pre>
                    </li>
                  ))}
                </ol>
                <p className="mt-3 text-[11px] text-muted leading-relaxed">
                  First <code className="font-mono bg-hover px-1 py-0.5 rounded">azd up</code> takes
                  ~12–18 min (Foundry account + project + ACR + agent build). Subsequent
                  {" "}<code className="font-mono bg-hover px-1 py-0.5 rounded">azd deploy</code> is &lt; 2 min.
                </p>
              </section>

              {/* Footer / troubleshooting */}
              <section className="rounded-xl border border-border-soft bg-surface-2 px-4 py-3">
                <p className="text-[12px] text-muted leading-relaxed">
                  <strong className="text-text">Stuck?</strong> The bundle&apos;s
                  {" "}<code className="font-mono bg-hover text-text px-1 py-0.5 rounded">README.md</code> covers the
                  three most common gotchas: 401 on first invoke (RBAC propagation, wait 5–15 min),
                  <em> session_not_ready</em> 424 (container crash — check
                  {" "}<code className="font-mono bg-hover text-text px-1 py-0.5 rounded">azd ai agent monitor --session-id</code>),
                  and region <em>experience not available</em> (try
                  {" "}<code className="font-mono bg-hover text-text px-1 py-0.5 rounded">swedencentral</code>).
                </p>
              </section>
            </div>
          ) : tab === "consistency" ? (
            /* ── Consistency Analysis tab ── */
            <div className="max-w-4xl space-y-6">
              {/* Controls */}
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
                <button
                  onClick={handleRunAnalysis}
                  disabled={analysisLoading}
                  className="flex items-center gap-2 px-5 py-2.5 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {analysisLoading ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-2 border-white/30 border-t-white" />
                      Analyzing...
                    </>
                  ) : (
                    <>
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                      </svg>
                      Run Analysis
                    </>
                  )}
                </button>
                <label className="flex items-center gap-2 text-sm text-text cursor-pointer">
                  <input
                    type="checkbox"
                    checked={includeDisabled}
                    onChange={(e) => setIncludeDisabled(e.target.checked)}
                    className="rounded border-border-soft dark:border-slate-600 text-accent focus:ring-accent"
                  />
                  Include disabled skills
                </label>
              </div>

              {/* Loading state */}
              {analysisLoading && (
                <div className="flex flex-col items-center justify-center py-16 animate-fade-in">
                  <div className="relative mb-6">
                    <div className="w-16 h-16 rounded-2xl bg-accent flex items-center justify-center">
                      <div className="animate-spin rounded-full h-8 w-8 border-2 border-accent-fg/30 border-t-accent-fg" />
                    </div>
                  </div>
                  <p className="text-sm text-muted">Analyzing system prompt and {skills.length} skills for inconsistencies...</p>
                  <p className="text-xs text-muted mt-1">This may take 10-30 seconds</p>
                </div>
              )}

              {/* Results */}
              {analysisResult && !analysisLoading && (
                <div className="space-y-6 animate-fade-in">
                  {/* Score + Summary card */}
                  <div className="bg-surface border border-border-soft rounded-2xl p-6">
                    <div className="flex items-start gap-6">
                      {/* Score ring */}
                      <div className="flex-shrink-0">
                        <div className={`relative w-20 h-20 rounded-full flex items-center justify-center border-4 ${
                          analysisResult.overallScore >= 90 ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-500/10" :
                          analysisResult.overallScore >= 70 ? "border-blue-500 bg-blue-50 dark:bg-blue-500/10" :
                          analysisResult.overallScore >= 50 ? "border-amber-500 bg-amber-50 dark:bg-amber-500/10" :
                          "border-red-500 bg-red-50 dark:bg-red-500/10"
                        }`}>
                          <div className="text-center">
                            <span className={`text-2xl font-bold ${
                              analysisResult.overallScore >= 90 ? "text-emerald-600 dark:text-emerald-400" :
                              analysisResult.overallScore >= 70 ? "text-blue-600 dark:text-blue-400" :
                              analysisResult.overallScore >= 50 ? "text-amber-600 dark:text-amber-400" :
                              "text-red-600 dark:text-red-400"
                            }`}>{analysisResult.overallScore}</span>
                            <span className="block text-[10px] text-muted -mt-0.5">/ 100</span>
                          </div>
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="text-base font-semibold text-text mb-1">
                          {analysisResult.overallScore >= 90 ? "Excellent" :
                           analysisResult.overallScore >= 70 ? "Good" :
                           analysisResult.overallScore >= 50 ? "Needs Attention" :
                           "Significant Issues"}
                        </h3>
                        <p className="text-sm text-text leading-relaxed">{analysisResult.summary}</p>
                        <div className="flex items-center gap-4 mt-3 text-xs text-muted">
                          <span>{analysisResult.issues.length} issue{analysisResult.issues.length !== 1 ? "s" : ""} found</span>
                          <span>{analysisResult.strengths.length} strength{analysisResult.strengths.length !== 1 ? "s" : ""}</span>
                          <span>{(analysisResult.durationMs / 1000).toFixed(1)}s analysis time</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Issue stats pills */}
                  {analysisResult.issues.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => setIssueFilter("all")}
                        className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-all ${
                          issueFilter === "all"
                            ? "bg-slate-900 dark:bg-white/[0.12] text-white border-transparent"
                            : "bg-white dark:bg-white/[0.03] text-slate-600 dark:text-slate-400 border-slate-200 dark:border-white/[0.08] hover:bg-slate-50 dark:hover:bg-white/[0.06]"
                        }`}
                      >
                        All ({analysisResult.issues.length})
                      </button>
                      {analysisResult.issues.filter(i => i.severity === "critical").length > 0 && (
                        <button
                          onClick={() => setIssueFilter("critical")}
                          className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-all ${
                            issueFilter === "critical"
                              ? "bg-red-500 text-white border-transparent"
                              : "text-red-600 dark:text-red-400 border-red-200 dark:border-red-500/20 hover:bg-red-50 dark:hover:bg-red-500/10"
                          }`}
                        >
                          Critical ({analysisResult.issues.filter(i => i.severity === "critical").length})
                        </button>
                      )}
                      {analysisResult.issues.filter(i => i.severity === "warning").length > 0 && (
                        <button
                          onClick={() => setIssueFilter("warning")}
                          className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-all ${
                            issueFilter === "warning"
                              ? "bg-amber-500 text-white border-transparent"
                              : "text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-500/20 hover:bg-amber-50 dark:hover:bg-amber-500/10"
                          }`}
                        >
                          Warning ({analysisResult.issues.filter(i => i.severity === "warning").length})
                        </button>
                      )}
                      {analysisResult.issues.filter(i => i.severity === "info").length > 0 && (
                        <button
                          onClick={() => setIssueFilter("info")}
                          className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-all ${
                            issueFilter === "info"
                              ? "bg-blue-500 text-white border-transparent"
                              : "text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-500/20 hover:bg-blue-50 dark:hover:bg-blue-500/10"
                          }`}
                        >
                          Info ({analysisResult.issues.filter(i => i.severity === "info").length})
                        </button>
                      )}
                    </div>
                  )}

                  {/* Issues list */}
                  {analysisResult.issues.length > 0 && (
                    <div className="space-y-3">
                      <h4 className="text-sm font-semibold text-text">Issues</h4>
                      {analysisResult.issues
                        .filter(issue => issueFilter === "all" || issue.severity === issueFilter)
                        .map((issue, idx) => {
                          const originalIdx = analysisResult.issues.indexOf(issue);
                          return (
                        <div
                          key={idx}
                          className="bg-surface border border-border-soft rounded-xl overflow-hidden transition-all"
                        >
                          <button
                            onClick={() => setExpandedIssue(expandedIssue === originalIdx ? null : originalIdx)}
                            className="w-full flex items-start gap-3 px-4 py-3.5 text-left hover:bg-hover transition-all"
                          >
                            {/* Severity icon */}
                            <div className={`flex-shrink-0 w-6 h-6 rounded-lg flex items-center justify-center mt-0.5 ${
                              issue.severity === "critical" ? "bg-red-100 dark:bg-red-500/10" :
                              issue.severity === "warning" ? "bg-amber-100 dark:bg-amber-500/10" :
                              "bg-blue-100 dark:bg-blue-500/10"
                            }`}>
                              {issue.severity === "critical" ? (
                                <svg className="w-3.5 h-3.5 text-red-500" fill="currentColor" viewBox="0 0 20 20">
                                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                                </svg>
                              ) : issue.severity === "warning" ? (
                                <svg className="w-3.5 h-3.5 text-amber-500" fill="currentColor" viewBox="0 0 20 20">
                                  <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                                </svg>
                              ) : (
                                <svg className="w-3.5 h-3.5 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clipRule="evenodd" />
                                </svg>
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-sm font-medium text-text">{issue.title}</span>
                                <span className={`text-[10px] px-1.5 py-0.5 rounded-md font-medium uppercase tracking-wide ${
                                  issue.category === "contradiction" ? "bg-red-100 dark:bg-red-500/10 text-red-600 dark:text-red-400" :
                                  issue.category === "overlap" ? "bg-purple-100 dark:bg-purple-500/10 text-purple-600 dark:text-purple-400" :
                                  issue.category === "gap" ? "bg-orange-100 dark:bg-orange-500/10 text-orange-600 dark:text-orange-400" :
                                  issue.category === "terminology" ? "bg-cyan-100 dark:bg-cyan-500/10 text-cyan-600 dark:text-cyan-400" :
                                  issue.category === "tone" ? "bg-pink-100 dark:bg-pink-500/10 text-pink-600 dark:text-pink-400" :
                                  issue.category === "ambiguity" ? "bg-yellow-100 dark:bg-yellow-500/10 text-yellow-600 dark:text-yellow-400" :
                                  "bg-slate-100 dark:bg-slate-500/10 text-slate-600 dark:text-slate-400"
                                }`}>
                                  {issue.category}
                                </span>
                              </div>
                              {expandedIssue !== originalIdx && (
                                <p className="text-xs text-muted mt-1 line-clamp-1">{issue.description}</p>
                              )}
                            </div>
                            <svg className={`w-4 h-4 text-slate-400 flex-shrink-0 mt-1 transition-transform ${expandedIssue === originalIdx ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                            </svg>
                          </button>
                          {expandedIssue === originalIdx && (
                            <div className="px-4 pb-4 pt-0 border-t border-border-soft animate-fade-in">
                              <div className="pl-9 space-y-3 pt-3">
                                <p className="text-sm text-text leading-relaxed">{issue.description}</p>
                                {issue.affectedSkills.length > 0 && (
                                  <div>
                                    <span className="text-xs font-medium text-muted">Affected skills:</span>
                                    <div className="flex flex-wrap gap-1.5 mt-1">
                                      {issue.affectedSkills.map((skill) => (
                                        <span key={skill} className="text-xs px-2 py-0.5 bg-surface-2 text-text rounded-md font-mono">
                                          {skill}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                )}
                                {issue.recommendation && (
                                  <div className="bg-emerald-50 dark:bg-emerald-500/[0.06] border border-emerald-100 dark:border-emerald-500/10 rounded-lg px-3 py-2.5">
                                    <span className="text-[10px] font-semibold text-emerald-700 dark:text-emerald-400 uppercase tracking-wide">Recommendation</span>
                                    <p className="text-sm text-emerald-800 dark:text-emerald-300 mt-0.5 leading-relaxed">{issue.recommendation}</p>
                                  </div>
                                )}

                                {/* Apply Fix button & result */}
                                {fixResults[originalIdx] ? (
                                  <div className={`rounded-lg px-3 py-2.5 border ${
                                    fixResults[originalIdx].success
                                      ? "bg-emerald-50 dark:bg-emerald-500/[0.06] border-emerald-200 dark:border-emerald-500/10"
                                      : "bg-red-50 dark:bg-red-500/[0.06] border-red-200 dark:border-red-500/10"
                                  }`}>
                                    {fixResults[originalIdx].success ? (
                                      <div className="space-y-1">
                                        <div className="flex items-center gap-1.5">
                                          <svg className="w-3.5 h-3.5 text-emerald-500" fill="currentColor" viewBox="0 0 20 20">
                                            <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clipRule="evenodd" />
                                          </svg>
                                          <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">Fix applied</span>
                                        </div>
                                        {fixResults[originalIdx].changes.map((change, ci) => (
                                          <p key={ci} className="text-xs text-emerald-700 dark:text-emerald-300 pl-5">{change.summary}</p>
                                        ))}
                                      </div>
                                    ) : (
                                      <div className="flex items-center gap-1.5">
                                        <svg className="w-3.5 h-3.5 text-red-500" fill="currentColor" viewBox="0 0 20 20">
                                          <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                                        </svg>
                                        <span className="text-xs text-red-700 dark:text-red-400">{fixResults[originalIdx].error}</span>
                                      </div>
                                    )}
                                  </div>
                                ) : (
                                  <button
                                    onClick={(e) => { e.stopPropagation(); handleApplyFix(issue, originalIdx); }}
                                    disabled={fixingIssue !== null}
                                    className="flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-all bg-indigo-50 dark:bg-indigo-500/[0.08] text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-500/20 hover:bg-indigo-100 dark:hover:bg-indigo-500/[0.14] disabled:opacity-50 disabled:cursor-not-allowed"
                                  >
                                    {fixingIssue === originalIdx ? (
                                      <>
                                        <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                                        </svg>
                                        Applying fix…
                                      </>
                                    ) : (
                                      <>
                                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                          <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17l-5.59-5.59a2 2 0 112.83-2.83l4.17 4.17 8.17-8.17a2 2 0 112.83 2.83L11.42 15.17z" />
                                        </svg>
                                        Apply Fix
                                      </>
                                    )}
                                  </button>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                          );
                        })}
                    </div>
                  )}

                  {/* Strengths */}
                  {analysisResult.strengths.length > 0 && (
                    <div className="space-y-3">
                      <h4 className="text-sm font-semibold text-text">Strengths</h4>
                      <div className="bg-surface border border-border-soft rounded-xl divide-y divide-slate-100 dark:divide-white/[0.04]">
                        {analysisResult.strengths.map((strength, idx) => (
                          <div key={idx} className="flex items-start gap-3 px-4 py-3">
                            <div className="flex-shrink-0 w-5 h-5 rounded-full bg-emerald-100 dark:bg-emerald-500/10 flex items-center justify-center mt-0.5">
                              <svg className="w-3 h-3 text-emerald-500" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clipRule="evenodd" />
                              </svg>
                            </div>
                            <p className="text-sm text-text leading-relaxed">{strength}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Empty state */}
              {!analysisResult && !analysisLoading && (
                <div className="flex flex-col items-center justify-center py-16">
                  <div className="w-16 h-16 rounded-2xl bg-accent-soft flex items-center justify-center mb-4">
                    <svg className="w-8 h-8 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                    </svg>
                  </div>
                  <h3 className="text-base font-semibold text-text mb-1">Consistency Checker</h3>
                  <p className="text-sm text-muted text-center max-w-md leading-relaxed">
                    Analyzes your system prompt and skill definitions using AI to detect contradictions,
                    overlapping responsibilities, terminology drift, coverage gaps, and other configuration
                    issues that could confuse the LLM at runtime.
                  </p>
                  <button
                    onClick={handleRunAnalysis}
                    className="mt-6 flex items-center gap-2 px-5 py-2.5 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
                    </svg>
                    Run First Analysis
                  </button>
                </div>
              )}
            </div>
          ) : loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent" />
            </div>

          ) : showCreate ? (
            /* ── Create view ── */
            <div className="max-w-3xl space-y-5">

              <div>
                <label className="block text-sm font-medium text-text mb-1.5">
                  Name <span className="text-muted">(lowercase, hyphens only)</span>
                </label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="my-new-skill"
                  className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-text mb-1.5">
                  Description
                </label>
                <input
                  type="text"
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="What this skill does"
                  className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-text mb-1.5">
                  Instructions (SKILL.md content)
                </label>
                <textarea
                  value={newInstructions}
                  onChange={(e) => setNewInstructions(e.target.value)}
                  rows={16}
                  placeholder="## Instructions&#10;&#10;1. Accept a query...&#10;2. Process it..."
                  className="w-full px-4 py-3 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all resize-y"
                />
              </div>

              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowCreate(false)}
                  className="px-4 py-2 text-sm text-muted bg-surface-2 border border-border-soft rounded-xl hover:bg-hover transition-all font-medium"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreate}
                  disabled={!newName.trim()}
                  className="px-4 py-2 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium disabled:opacity-50"
                >
                  Create Skill
                </button>
              </div>
            </div>
          ) : (
            /* ── Skills list ── */
            <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
              {skills.length === 0 ? (
                <div className="col-span-full text-center py-16">
                  <div className="w-16 h-16 mx-auto rounded-2xl bg-surface-2 flex items-center justify-center mb-4">
                    <svg className="w-8 h-8 text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M14.25 6.087c0-.355.186-.676.401-.959.221-.29.349-.634.349-1.003 0-1.036-1.007-1.875-2.25-1.875s-2.25.84-2.25 1.875c0 .369.128.713.349 1.003.215.283.401.604.401.959v0a.64.64 0 01-.657.643 48.39 48.39 0 01-4.163-.3c.186 1.613.166 3.532-1.005 3.532" />
                    </svg>
                  </div>
                  <p className="text-sm text-muted font-medium">No skills configured</p>
                  <p className="text-xs text-muted mt-1">Add your first skill to get started</p>
                </div>
              ) : (
                skills.map((skill) => {
                  const isEditing = editingSkill?.name === skill.name;
                  return (
                  <div
                    key={skill.name}
                    className={`flex flex-col p-5 border rounded-2xl transition-all ${
                      isEditing
                        ? "col-span-full border-accent bg-surface shadow-lg ring-1 ring-accent/30"
                        : "border-border-soft bg-surface hover:border-border hover:shadow-card-hover group"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3 mb-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-semibold text-sm text-text truncate">
                            {skill.name}
                          </span>
                          {(skill.fileCount ?? 0) > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-[10px] text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-500/10 px-1.5 py-0.5 rounded-full flex-shrink-0">
                              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                              </svg>
                              {skill.fileCount}
                            </span>
                          )}
                        </div>
                        {!isEditing && (
                          <>
                            <p className="text-xs text-muted line-clamp-2">
                              {skill.description || "No description"}
                            </p>
                            <div className="flex items-center gap-2 mt-1.5">
                              <p className="text-[10px] text-muted font-mono">{skill.toolName}</p>
                              <SourceBadge source={skill.source} />
                            </div>
                          </>
                        )}
                      </div>
                      {/* Toggle */}
                      <button
                        onClick={() => handleToggle(skill)}
                        className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full transition-colors ${
                          skill.enabled ? "bg-accent" : "bg-border"
                        }`}
                      >
                        <span
                          className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform mt-0.5 ${
                            skill.enabled ? "translate-x-5 ml-0.5" : "translate-x-0.5"
                          }`}
                        />
                      </button>
                    </div>

                    {isEditing ? (
                      /* ── Inline Edit Form ── */
                      <div className="space-y-5 pt-3 border-t border-border-soft">
                        <div>
                          <label className="block text-sm font-medium text-text mb-1.5">Description</label>
                          <input
                            type="text"
                            value={editingSkill.description}
                            onChange={(e) => setEditingSkill({ ...editingSkill, description: e.target.value })}
                            className="w-full px-3 py-2 bg-surface-2 border border-border-soft rounded-xl text-sm text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-text mb-1.5">Instructions (SKILL.md content)</label>
                          <textarea
                            value={editingSkill.instructions}
                            onChange={(e) => setEditingSkill({ ...editingSkill, instructions: e.target.value })}
                            rows={20}
                            className="w-full px-4 py-3 bg-surface-2 border border-border-soft rounded-xl text-sm text-text font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent transition-all resize-y"
                          />
                        </div>

                        {/* Files & Scripts section */}
                        <div>
                          <div className="flex items-center justify-between mb-2">
                            <label className="block text-sm font-medium text-text">
                              Scripts &amp; Files
                              {skillFiles.length > 0 && (
                                <span className="ml-1.5 text-xs font-normal text-muted">({skillFiles.length})</span>
                              )}
                            </label>
                            {!showUploadForm && (
                              <button
                                type="button"
                                onClick={() => setShowUploadForm(true)}
                                className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-accent hover:bg-accent-hover rounded-xl transition-all border border-accent"
                              >
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                                </svg>
                                Upload
                              </button>
                            )}
                          </div>
                          {showUploadForm && (
                            <div className="flex items-center gap-2 mb-3 p-2.5 bg-surface-2 border border-border-soft rounded-xl">
                              <div className="flex-1 flex items-center gap-1.5">
                                <span className="text-xs text-muted font-mono flex-shrink-0">path:</span>
                                <input
                                  type="text"
                                  value={uploadPath}
                                  onChange={(e) => setUploadPath(e.target.value)}
                                  placeholder="scripts/"
                                  className="flex-1 px-2 py-1 text-xs font-mono border border-border-soft rounded focus:outline-none focus:ring-1 focus:ring-accent min-w-0"
                                  onKeyDown={(e) => e.key === "Escape" && (setShowUploadForm(false), setUploadPath(""))}
                                />
                              </div>
                              <label className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-accent-fg bg-accent hover:bg-accent-hover rounded-xl cursor-pointer transition-colors flex-shrink-0">
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                                </svg>
                                Choose file
                                <input ref={fileInputRef} type="file" className="hidden" onChange={handleUploadFile} />
                              </label>
                              <button
                                type="button"
                                onClick={() => { setShowUploadForm(false); setUploadPath(""); }}
                                className="text-muted hover:text-text transition-colors flex-shrink-0"
                              >
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                              </button>
                            </div>
                          )}
                          {filesLoading ? (
                            <div className="flex items-center gap-2 py-3 text-xs text-muted">
                              <div className="animate-spin rounded-full h-3.5 w-3.5 border-b-2 border-border" />
                              Loading files…
                            </div>
                          ) : skillFiles.length === 0 ? (
                            <p className="text-xs text-muted text-center py-4 border border-dashed border-border-soft rounded-xl">
                              No files yet. Upload scripts or other supporting files for this skill.
                            </p>
                          ) : (
                            <div className="space-y-1.5">
                              {skillFiles.map((file) => (
                                <div key={file.path} className="border border-border-soft rounded-xl overflow-hidden">
                                  <div
                                    className="flex items-center gap-2 px-3 py-2 bg-surface-2 hover:bg-hover cursor-pointer transition-colors select-none"
                                    onClick={() => setExpandedFile(expandedFile === file.path ? null : file.path)}
                                  >
                                    <svg className="w-3.5 h-3.5 text-indigo-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                    </svg>
                                    <span className="text-xs font-mono text-muted flex-1 truncate">{file.path}</span>
                                    <svg
                                      className={`w-3.5 h-3.5 text-slate-400 transition-transform flex-shrink-0 ${expandedFile === file.path ? "rotate-180" : ""}`}
                                      fill="none" viewBox="0 0 24 24" stroke="currentColor"
                                    >
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                    </svg>
                                    <button
                                      onClick={(e) => { e.stopPropagation(); handleDeleteFile(file.path); }}
                                      className="p-0.5 text-muted hover:text-red-500 transition-colors flex-shrink-0"
                                      title="Delete file"
                                    >
                                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                      </svg>
                                    </button>
                                  </div>
                                  {expandedFile === file.path && (
                                    <pre className="text-xs font-mono p-3 bg-surface-2 text-text overflow-x-auto max-h-52 overflow-y-auto whitespace-pre leading-relaxed">
                                      {file.content || "(binary or empty file)"}
                                    </pre>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>

                        <div className="flex justify-end gap-3 pt-2">
                          <button
                            onClick={() => setEditingSkill(null)}
                            className="px-5 py-2.5 text-sm text-muted bg-surface-2 border border-border-soft rounded-xl hover:bg-hover transition-all font-medium"
                          >
                            Cancel
                          </button>
                          <button
                            onClick={handleSaveEdit}
                            className="px-5 py-2.5 text-sm text-accent-fg bg-accent rounded-xl transition-all shadow-sm font-medium"
                          >
                            Save Changes
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 mt-auto pt-3 border-t border-border-soft">
                        <button
                          onClick={() => setEditingSkill(skill)}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-text hover:text-accent hover:bg-accent-hover rounded-lg transition-all font-medium"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                          </svg>
                          Edit
                        </button>
                        <button
                          onClick={() => handleDelete(skill.name)}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-muted hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-lg transition-all font-medium"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                  );
                })
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
