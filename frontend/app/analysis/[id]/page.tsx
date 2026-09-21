"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";

import { AnalysisProgress } from "@/components/AnalysisProgress";
import { AnalysisResults } from "@/components/AnalysisResults";

export default function AnalysisPage() {
  const params = useParams<{ id: string }>();
  const analysisId = params.id;

  // Read access is public by analysis_id; a locally stored session_id only
  // marks this browser as the uploader (a UI hint — the question and resume
  // endpoints still enforce it).
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

        {sessionChecked && (
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
                  isOwner={sessionId !== null}
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
