"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { THEMES, useTheme } from "./ThemeProvider";

export function ThemePicker() {
  const { theme, mode, setTheme, toggleMode } = useTheme();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    if (!open || !triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    setPos({ top: r.top - 8, left: r.left });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (
        triggerRef.current?.contains(e.target as Node) ||
        popoverRef.current?.contains(e.target as Node)
      ) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = THEMES.find((t) => t.id === theme) ?? THEMES[0];

  return (
    <>
      <button
        ref={triggerRef}
        onClick={() => setOpen((v) => !v)}
        title={`Theme: ${current.label} · ${mode}`}
        className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-hover transition-colors"
        aria-label="Change theme"
      >
        <div className="flex gap-0.5">
          {current.swatches.map((c) => (
            <span
              key={c}
              className="w-2.5 h-2.5 rounded-sm border border-border-soft"
              style={{ background: c }}
            />
          ))}
        </div>
      </button>

      {open && pos && typeof document !== "undefined" && createPortal(
        <div
          ref={popoverRef}
          className="fixed z-[300] w-[280px] bg-surface border border-border rounded-xl shadow-card overflow-hidden animate-scale-in"
          style={{ top: pos.top, left: pos.left, transform: "translateY(-100%)" }}
        >
          <div className="px-3 py-2.5 border-b border-border-soft flex items-center justify-between">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">Theme</div>
            <button
              onClick={toggleMode}
              className="px-2 py-1 rounded-md text-[11px] font-medium text-text hover:bg-hover transition-colors flex items-center gap-1.5"
              title={`Switch to ${mode === "dark" ? "light" : "dark"} mode`}
            >
              {mode === "dark" ? (
                <>
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
                  </svg>
                  Dark
                </>
              ) : (
                <>
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" />
                  </svg>
                  Light
                </>
              )}
            </button>
          </div>
          <div className="max-h-[420px] overflow-y-auto py-1">
            {THEMES.map((t) => {
              const active = t.id === theme;
              return (
                <button
                  key={t.id}
                  onClick={() => { setTheme(t.id); }}
                  className={`w-full flex items-center gap-3 px-3 py-2 hover:bg-hover transition-colors text-left ${active ? "bg-accent-soft" : ""}`}
                >
                  <div className="flex gap-0.5 flex-shrink-0">
                    {t.swatches.map((c) => (
                      <span
                        key={c}
                        className="w-4 h-4 rounded-sm border border-border-soft"
                        style={{ background: c }}
                      />
                    ))}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] font-medium text-text truncate">{t.label}</div>
                    <div className="text-[10px] text-muted truncate">{t.tagline}</div>
                  </div>
                  {active && (
                    <svg className="w-3.5 h-3.5 text-accent flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                  )}
                </button>
              );
            })}
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
