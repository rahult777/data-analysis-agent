import "server-only";

import { isSnapshot } from "@/lib/mode";
import { readSnapshot, type Snapshot } from "@/lib/snapshot-rules.mjs";
import type { SnapshotAnalysis } from "@/lib/types";

// The public snapshot build's data (`npm run build:public`), read at build
// time and never shipped as code. Every rule in lib/snapshot-rules.mjs runs on
// the first call, which app/analysis/[id]/page.tsx makes in
// generateStaticParams: a broken snapshot fails the build with its own message
// before Next's "missing generateStaticParams()". Local mode never calls this.
let snapshot: Snapshot | undefined;

function load(): Snapshot {
  if (!isSnapshot) {
    throw new Error("The snapshot is read only in the public build (npm run build:public).");
  }
  // `next build` runs in frontend/, so SNAPSHOT_DIR resolves against it.
  snapshot ??= readSnapshot(process.cwd(), process.env);
  return snapshot;
}

export function snapshotAnalyses(): SnapshotAnalysis[] {
  return load().analyses;
}

export function snapshotAnalysis(id: string): SnapshotAnalysis {
  const analysis = load().analyses.find((a) => a.id === id);
  if (!analysis) throw new Error(`Snapshot: no analysis ${id} in the manifest.`);
  return analysis;
}
