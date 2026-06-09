"use client";

import { createContext, useContext, useEffect, useState } from "react";

export type Mode = "light" | "dark";

export type ThemeName =
  | "anthropic-peach"
  | "tokyo-night"
  | "catppuccin"
  | "rose-pine"
  | "newsprint"
  | "brutalist-yellow"
  | "cursor-cyber"
  | "nord";

export const THEMES: { id: ThemeName; label: string; tagline: string; swatches: [string, string, string] }[] = [
  { id: "anthropic-peach",  label: "Anthropic Peach",  tagline: "Warm cream + sienna",        swatches: ["#f7f3ec", "#cc785c", "#1f1d1a"] },
  { id: "tokyo-night",      label: "Tokyo Night",      tagline: "Midnight + mauve",           swatches: ["#1a1b26", "#bb9af7", "#e0af68"] },
  { id: "catppuccin",       label: "Catppuccin",       tagline: "Pastel-on-dark",             swatches: ["#1e1e2e", "#cba6f7", "#fab387"] },
  { id: "rose-pine",        label: "Rosé Pine",        tagline: "Dusky purple + rose",        swatches: ["#191724", "#c4a7e7", "#ebbcba"] },
  { id: "newsprint",        label: "Newsprint",        tagline: "Cream paper + ink + red",    swatches: ["#f7f3e9", "#1a1a1a", "#a02929"] },
  { id: "brutalist-yellow", label: "Brutalist Yellow", tagline: "Mono + electric yellow",     swatches: ["#ffffff", "#000000", "#facc15"] },
  { id: "cursor-cyber",     label: "Cursor Cyber",     tagline: "Near-black + magenta + cyan", swatches: ["#0a0a14", "#f038a0", "#22d3ee"] },
  { id: "nord",             label: "Nord",             tagline: "Icy Scandinavian classic",   swatches: ["#2e3440", "#88c0d0", "#d08770"] },
];

const DEFAULT_THEME: ThemeName = "anthropic-peach";

interface ThemeContextValue {
  theme: ThemeName;
  mode: Mode;
  setTheme: (t: ThemeName) => void;
  setMode: (m: Mode) => void;
  toggleMode: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: DEFAULT_THEME,
  mode: "light",
  setTheme: () => {},
  setMode: () => {},
  toggleMode: () => {},
});

export function useTheme() {
  return useContext(ThemeContext);
}

const THEME_IDS = new Set(THEMES.map((t) => t.id));

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeName>(DEFAULT_THEME);
  const [mode, setModeState] = useState<Mode>("light");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const storedTheme = localStorage.getItem("kratos-theme-name");
    if (storedTheme && THEME_IDS.has(storedTheme as ThemeName)) {
      setThemeState(storedTheme as ThemeName);
    }
    const storedMode = localStorage.getItem("kratos-theme-mode");
    if (storedMode === "dark" || storedMode === "light") {
      setModeState(storedMode);
    } else if (typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      setModeState("dark");
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    if (mode === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    if (hydrated) {
      localStorage.setItem("kratos-theme-name", theme);
      localStorage.setItem("kratos-theme-mode", mode);
    }
  }, [theme, mode, hydrated]);

  const setTheme = (t: ThemeName) => setThemeState(t);
  const setMode = (m: Mode) => setModeState(m);
  const toggleMode = () => setModeState((m) => (m === "dark" ? "light" : "dark"));

  return (
    <ThemeContext.Provider value={{ theme, mode, setTheme, setMode, toggleMode }}>
      {children}
    </ThemeContext.Provider>
  );
}
