import type { ReactElement } from "react";

import { GITHUB_URL, SITE_NAME } from "@/lib/site";

// The public site's header: the mark and the name, linking home, and the
// GitHub repository. A server component, rendered by the root layout in the
// public build only (app/layout.tsx); it reads lib/site.ts, so never import it
// into client code. Plain <a> links (owner ruling D7), and no motion.
// The mark is app/icon.svg's path, drawn inline in the text color: an <img>
// here would change what the chart tests count.
export function SiteHeader(): ReactElement {
  return (
    <header className="w-full border-b border-border/60 px-6 py-2">
      <div className="mx-auto flex w-full max-w-4xl items-center justify-between gap-4">
        <a href="/" className="inline-flex min-h-11 items-center gap-2.5 text-foreground hover:text-primary">
          <svg viewBox="0 0 32 32" fill="currentColor" aria-hidden="true" className="size-6 shrink-0">
            <path d="M4 14h24v4H4ZM16 8l8 8l-8 8l-8-8Z" />
          </svg>
          <span className="text-xl italic leading-none" style={{ fontFamily: "var(--font-display)" }}>
            {SITE_NAME}
          </span>
        </a>
        <a href={GITHUB_URL} className="inline-flex min-h-11 items-center text-sm text-muted-foreground hover:text-foreground">
          GitHub
        </a>
      </div>
    </header>
  );
}
