/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      // ── Semantic theme tokens (driven by CSS variables in globals.css) ──
      // Use these everywhere instead of literal palette colors.
      colors: {
        // Surfaces & text
        bg:           "var(--bg)",
        surface: {
          DEFAULT:    "var(--surface)",
          2:          "var(--surface-2)",
        },
        border: {
          DEFAULT:    "var(--border)",
          soft:       "var(--border-soft)",
        },
        hover:        "var(--hover)",
        text: {
          DEFAULT:    "var(--text)",
          strong:     "var(--text-strong)",
        },
        muted: {
          DEFAULT:    "var(--muted)",
          strong:     "var(--muted-strong)",
        },
        // Brand / interactive
        accent: {
          DEFAULT:    "var(--accent)",
          hover:      "var(--accent-hover)",
          fg:         "var(--accent-fg)",
          soft:       "var(--accent-soft)",
        },
        // Ask-user (H-I-T-L) signal
        ask: {
          DEFAULT:    "var(--ask-accent)",
          fg:         "var(--ask-accent-fg)",
          border:     "var(--ask-border)",
          bg:         "var(--ask-bg)",
        },
        // Status semantics — reused from Tailwind defaults so they stay
        // legible regardless of theme. Don't theme-couple status colors.
        success: { 500: "#10b981", 600: "#059669" },
        warning: { 500: "#f59e0b", 600: "#d97706" },
        danger:  { 500: "#ef4444", 600: "#dc2626" },
      },
      fontFamily: {
        sans: ['var(--font-display)', 'Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
        mono: ['var(--font-mono)', '"JetBrains Mono"', '"Fira Code"', 'Consolas', 'monospace'],
      },
      boxShadow: {
        'card':       'var(--shadow-card)',
        'card-hover': '0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.06)',
        'inner-glow': 'inset 0 1px 0 rgba(255, 255, 255, 0.05)',
      },
      animation: {
        'fade-in':           'fadeIn 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-up':          'slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-in-left':     'slideInLeft 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'pulse-slow':        'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'scale-in':          'scaleIn 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-up-stagger':  'slideUpStagger 0.5s cubic-bezier(0.16, 1, 0.3, 1) both',
        'bounce-subtle':     'bounceSubtle 0.5s cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
      keyframes: {
        fadeIn:          { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        slideUp:         { '0%': { opacity: '0', transform: 'translateY(12px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        slideInLeft:     { '0%': { opacity: '0', transform: 'translateX(-8px)' }, '100%': { opacity: '1', transform: 'translateX(0)' } },
        scaleIn:         { '0%': { opacity: '0', transform: 'scale(0.95)' }, '100%': { opacity: '1', transform: 'scale(1)' } },
        slideUpStagger:  { '0%': { opacity: '0', transform: 'translateY(16px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        bounceSubtle:    { '0%': { transform: 'scale(0.95)' }, '40%': { transform: 'scale(1.02)' }, '100%': { transform: 'scale(1)' } },
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};
