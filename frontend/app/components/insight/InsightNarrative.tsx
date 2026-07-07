"use client";

import React from "react";
import { motion } from "framer-motion";
import { Volume2, VolumeX } from "lucide-react";
import ReactMarkdown from "react-markdown";

type InsightNarrativeProps = {
  text: string;
  isMuted: boolean;
  onToggleMute: () => void;
};

export function InsightNarrative({ text, isMuted, onToggleMute }: InsightNarrativeProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.15 }}
      className="mb-8"
    >
      <div className="text-base md:text-lg font-light text-[var(--text-secondary)] leading-relaxed tracking-normal">
        <ReactMarkdown
          components={{
            strong: ({ node, ...props }) => <span className="font-medium text-[var(--text-primary)]" {...props} />,
            h1: ({ node, ...props }) => <span className="font-medium text-[var(--text-primary)] text-lg block mb-2" {...props} />,
            h2: ({ node, ...props }) => <span className="font-medium text-[var(--text-primary)] text-base block mb-2" {...props} />,
            h3: ({ node, ...props }) => <span className="font-medium text-[var(--text-primary)] text-base block mb-2" {...props} />,
            p: ({ node, ...props }) => <span className="inline" {...props} />
          }}
        >
          {text}
        </ReactMarkdown>
      </div>
      <button
        type="button"
        onClick={onToggleMute}
        className="mt-4 flex items-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--accent-blue)] transition-colors"
      >
        {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4 text-[var(--accent-blue)]" />}
        <span>{isMuted ? "Voice summary off" : "Playing voice summary"}</span>
      </button>
    </motion.div>
  );
}
