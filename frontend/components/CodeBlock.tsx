"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

import { cn } from "@/lib/utils";

interface CodeBlockProps {
  code: string;
  language?: string;
  className?: string;
}

/**
 * Shared monospace code display with copy-to-clipboard.
 *
 * No syntax highlighting — no highlighter is installed and none is added
 * (see decisions.md). Used by InsightReport's Technical layer code_blocks
 * and QuestionInput's pandas_code display.
 */
export function CodeBlock({ code, language, className }: CodeBlockProps) {
  const [copied, setCopied] = useState<boolean>(false);

  async function handleCopy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API unavailable (e.g. non-secure context) — fail quietly.
    }
  }

  return (
    <div
      className={cn(
        "overflow-hidden rounded-md border border-border/60 bg-background/60",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border/60 bg-card/40 px-3 py-1.5">
        <span className="font-mono text-xs tracking-wide text-muted-foreground">
          {language ?? "code"}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? "Copied to clipboard" : "Copy code to clipboard"}
          className="inline-flex h-7 items-center gap-1.5 rounded px-2 text-xs text-muted-foreground transition-colors hover:text-foreground max-sm:h-11"
        >
          {copied ? (
            <>
              <Check className="size-3.5 text-green-500" aria-hidden />
              <span>Copied</span>
            </>
          ) : (
            <>
              <Copy className="size-3.5" aria-hidden />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="overflow-x-auto px-4 py-3 text-sm leading-relaxed">
        <code className="font-mono text-foreground/90">{code}</code>
      </pre>
    </div>
  );
}
