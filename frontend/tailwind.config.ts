import type { Config } from "tailwindcss";
import defaultTheme from "tailwindcss/defaultTheme";

// globals.css defines every token as a complete oklch() color (some with
// alpha), so the v3 channels + <alpha-value> pattern can't apply. Wrapping
// in color-mix keeps opacity modifiers (bg-card/40) working; v3 substitutes
// <alpha-value> as a plain string (1 or the modifier value).
const cssVarColor = (name: string): string =>
  `color-mix(in oklch, var(--${name}) calc(<alpha-value> * 100%), transparent)`;

const config: Config = {
  // layout.tsx forces `dark` on <html>; v3's default "media" would ignore it.
  darkMode: "selector",
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      // layout.tsx exposes DM Sans (body text, decisions.md 2026-05-16) as
      // --font-sans via next/font. Its value holds only DM Sans and its
      // metric-adjusted fallback, so v3's default stack stays as the final
      // fallback. Instrument Serif (--font-display) is applied to headings by
      // inline style and needs no mapping.
      fontFamily: {
        sans: ["var(--font-sans)", ...defaultTheme.fontFamily.sans],
      },
      colors: {
        background: cssVarColor("background"),
        foreground: cssVarColor("foreground"),
        card: { DEFAULT: cssVarColor("card"), foreground: cssVarColor("card-foreground") },
        popover: { DEFAULT: cssVarColor("popover"), foreground: cssVarColor("popover-foreground") },
        primary: { DEFAULT: cssVarColor("primary"), foreground: cssVarColor("primary-foreground") },
        secondary: { DEFAULT: cssVarColor("secondary"), foreground: cssVarColor("secondary-foreground") },
        muted: { DEFAULT: cssVarColor("muted"), foreground: cssVarColor("muted-foreground") },
        accent: { DEFAULT: cssVarColor("accent"), foreground: cssVarColor("accent-foreground") },
        destructive: cssVarColor("destructive"),
        border: cssVarColor("border"),
        input: cssVarColor("input"),
        ring: cssVarColor("ring"),
        chart: {
          1: cssVarColor("chart-1"), 2: cssVarColor("chart-2"), 3: cssVarColor("chart-3"),
          4: cssVarColor("chart-4"), 5: cssVarColor("chart-5"),
        },
        sidebar: {
          DEFAULT: cssVarColor("sidebar"),
          foreground: cssVarColor("sidebar-foreground"),
          primary: cssVarColor("sidebar-primary"),
          "primary-foreground": cssVarColor("sidebar-primary-foreground"),
          accent: cssVarColor("sidebar-accent"),
          "accent-foreground": cssVarColor("sidebar-accent-foreground"),
          border: cssVarColor("sidebar-border"),
          ring: cssVarColor("sidebar-ring"),
        },
        corr: {
          negative: cssVarColor("corr-negative"),
          neutral: cssVarColor("corr-neutral"),
          positive: cssVarColor("corr-positive"),
        },
      },
    },
  },
  plugins: [],
};
export default config;
