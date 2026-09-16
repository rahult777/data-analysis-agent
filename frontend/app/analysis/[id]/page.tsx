"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle } from "lucide-react";

import { AnalysisProgress } from "@/components/AnalysisProgress";
import { AnalysisResults } from "@/components/AnalysisResults";
import { Button } from "@/components/ui/button";

export default function AnalysisPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const analysisId = params.id;

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionChecked, setSessionChecked] = useState<boolean>(false);
  const [isComplete, setIsComplete] = useState<boolean>(false);

  useEffect(() => {
    const stored = localStorage.getItem(`session_id_${analysisId}`);
    setSessionId(stored);
    setSessionChecked(true);
  }, [analysisId]);

  return (
    <main className="min-h-screen w-full px-6 py-8 sm:py-12 md:py-16">
      <div
        className={`mx-auto flex w-full flex-col gap-12 transition-[max-width] duration-500 ${
          isComplete ? "max-w-4xl" : "max-w-2xl"
        }`}
      >
        <header className="flex flex-col gap-4 text-center">
          <h1
            className="text-4xl sm:text-5xl md:text-6xl italic leading-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Analysis
          </h1>
        </header>

        {sessionChecked && sessionId === null && (
          <motion.div
            role="alert"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="flex items-start gap-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-5 py-5 text-amber-200 md:px-6 md:py-6"
          >
            <AlertTriangle className="size-5 mt-0.5 shrink-0" aria-hidden />
            <div className="flex flex-col gap-4 flex-1 min-w-0">
              <p className="text-sm">
                Session not found. Please upload your file again.
              </p>
              <Button
                type="button"
                onClick={() => router.push("/")}
                aria-label="Return to upload page"
                className="self-start"
              >
                Return to upload
              </Button>
            </div>
          </motion.div>
        )}

        {sessionId !== null && (
          <AnimatePresence mode="wait" initial={false}>
            {!isComplete ? (
              <motion.div
                key="progress"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.3, ease: "easeOut" }}
              >
                <AnalysisProgress
                  analysisId={analysisId}
                  sessionId={sessionId}
                  onComplete={() => setIsComplete(true)}
                />
              </motion.div>
            ) : (
              <motion.div
                key="results"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.3, ease: "easeOut" }}
              >
                <AnalysisResults
                  analysisId={analysisId}
                  sessionId={sessionId}
                />
              </motion.div>
            )}
          </AnimatePresence>
        )}
      </div>
    </main>
  );
}
