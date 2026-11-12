import type { ReactElement } from "react";

import { GITHUB_PROFILE_URL, GITHUB_URL } from "@/lib/site";

const LINK = "inline-flex min-h-11 items-center text-foreground/90 underline underline-offset-4 hover:text-primary";

// The public site's footer: the source, the third-party notices (the static
// file public/third-party-notices.txt) and who built the site, linking to the
// owner's GitHub profile, which lib/site.ts derives from the repository's
// address. A server component, rendered by the root layout in the public
// build only; it reads lib/site.ts, so never import it into client code.
// Plain <a> links (owner ruling D7), and no motion.
export function SiteFooter(): ReactElement {
  return (
    <footer className="w-full border-t border-border/60 px-6 py-4">
      <div className="mx-auto flex w-full max-w-4xl flex-col text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:gap-8">
        <div className="flex flex-col sm:flex-row sm:gap-8">
          <a href={GITHUB_URL} className={LINK}>
            Source on GitHub
          </a>
          <a href="/third-party-notices.txt" className={LINK}>
            Third-party notices
          </a>
        </div>
        <p>
          Built by{" "}
          <a href={GITHUB_PROFILE_URL} className={LINK}>
            Rahul Tanikanti
          </a>
        </p>
      </div>
    </footer>
  );
}
