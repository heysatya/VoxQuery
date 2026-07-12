"use client";

import React, { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { Mic, ArrowRight } from "lucide-react";

type TranscriptReviewPanelProps = {
  /** The raw transcript exactly as the STT returned it. Never edited. */
  rawTranscript: string;
  /** The editable text the user can change before submitting. */
  editedText: string;
  /** Whether a pipeline turn is already in flight (disable actions). */
  disabled: boolean;
  onChange: (value: string) => void;
  onReRecord: () => void;
  onSubmit: () => void | Promise<void>;
};

/**
 * Transcript review panel — the execution boundary between voice capture and
 * query submission.
 *
 * Design contract:
 * - Raw transcript is preserved and shown above the editor.
 * - Editable text is what VoxQuery will actually execute.
 * - The panel makes it clear that execution has not started.
 * - "Ask VoxQuery" is the only action that triggers pipeline submission.
 * - "Re-record" returns to voice capture state.
 */
export function TranscriptReviewPanel({
  rawTranscript,
  editedText,
  disabled,
  onChange,
  onReRecord,
  onSubmit,
}: TranscriptReviewPanelProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Move keyboard focus into the review editor as soon as the panel appears.
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (!disabled && editedText.trim()) {
        void onSubmit();
      }
    }
  };

  return (
    <motion.section
      role="region"
      aria-label="Transcript review"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.35, ease: [0.23, 1, 0.32, 1] }}
      className="w-full max-w-xl mx-auto"
    >
      {/* Header */}
      <p className="text-xs font-semibold tracking-widest uppercase text-[var(--text-muted)] mb-3">
        I heard
      </p>

      {/* Raw transcript — immutable display */}
      <blockquote
        aria-label="Raw transcript"
        className="mb-4 px-4 py-3 rounded-xl bg-[var(--bg-surface)] border border-[var(--border)] text-sm text-[var(--text-secondary)] italic leading-relaxed"
      >
        &ldquo;{rawTranscript}&rdquo;
      </blockquote>

      {/* Editable transcript */}
      <label
        htmlFor="transcript-editor"
        className="block text-xs font-semibold tracking-widest uppercase text-[var(--text-muted)] mb-2"
      >
        Edit before submitting
      </label>
      <textarea
        id="transcript-editor"
        ref={textareaRef}
        aria-label="Editable transcript"
        value={editedText}
        disabled={disabled}
        rows={3}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Adjust the question if needed..."
        className="w-full px-4 py-3 bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-blue)] resize-none transition-colors disabled:opacity-50"
      />

      <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
        ⌘ Enter to submit &middot; Execution has not started
      </p>

      {/* Action row */}
      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          onClick={onReRecord}
          disabled={disabled}
          aria-label="Re-record"
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--accent-blue)]/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] transition-all disabled:opacity-50"
        >
          <Mic className="h-4 w-4" />
          Re-record
        </button>

        <button
          type="button"
          onClick={() => void onSubmit()}
          disabled={disabled || !editedText.trim()}
          aria-label="Ask VoxQuery"
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/85 text-sm text-white font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Ask VoxQuery
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </motion.section>
  );
}
