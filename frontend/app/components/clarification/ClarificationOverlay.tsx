"use client";

import React, { useEffect, useId, useRef } from "react";
import { motion } from "framer-motion";
import type { ClarificationState } from "../../../lib/types";

type ClarificationOverlayProps = {
  clarification: ClarificationState;
  onResolve: (selection: string | null) => void | Promise<void>;
};

export function ClarificationOverlay({
  clarification,
  onResolve
}: ClarificationOverlayProps) {
  const titleId = useId();
  const firstOptionRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    firstOptionRef.current?.focus();
  }, []);

  if (!clarification.pending) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        className="w-full max-w-lg glass-card overflow-hidden"
      >
        <div className="p-8 text-center space-y-6">
          <h2 id={titleId} className="text-xl font-medium text-[var(--text-primary)]">
            {clarification.question}
          </h2>


          <div className="space-y-3">
            {clarification.options.map((option, index) => (
              <button
                key={option}
                ref={index === 0 ? firstOptionRef : undefined}
                type="button"
                onClick={() => onResolve(option)}
                className="w-full p-4 text-left rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] hover:border-[var(--accent-blue)]/50 hover:bg-[var(--bg-elevated)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] transition-all text-[var(--text-primary)] font-medium"
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        <div className="p-4 border-t border-[var(--border)] text-center">
          <button
            type="button"
            onClick={() => onResolve(null)}
            className="text-sm text-[var(--text-muted)] hover:text-[var(--text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] font-medium transition-colors"
          >
            None of these — let me rephrase
          </button>
        </div>
      </motion.div>
    </div>
  );
}
