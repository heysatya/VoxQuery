"use client";

import React from "react";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import type { LastResult } from "../../../lib/types";

type FollowUpSuggestionsProps = {
  result: LastResult;
  onSelect: (question: string) => Promise<void>;
  disabled: boolean;
};

export function FollowUpSuggestions({ result, onSelect, disabled }: FollowUpSuggestionsProps) {
  const suggestions = result.proactiveQuestions.slice(0, 3);
  if (suggestions.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4, delay: 0.6 }}
      className="mt-8"
    >
      <p className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-widest mb-3">
        Ask a follow-up
      </p>
      <div className="flex flex-wrap gap-2">
        {suggestions.map((question, i) => (
          <motion.button
            key={question}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.7 + i * 0.1 }}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(question)}
            className="group flex items-center gap-2 px-4 py-2.5 rounded-full border border-[var(--border)] bg-[var(--bg-surface)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--accent-blue)] hover:bg-[var(--bg-elevated)] transition-all disabled:opacity-50"
          >
            <span>{question}</span>
            <ArrowRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-100 transition-opacity" />
          </motion.button>
        ))}
      </div>
    </motion.div>
  );
}
