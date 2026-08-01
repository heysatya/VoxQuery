"use client";

import React from "react";
import { Sparkles, Clock, ArrowRight } from "lucide-react";

interface PriorSessionMemoryCardProps {
  questions: string[];
  onSelectQuestion?: (question: string) => void;
}

export function PriorSessionMemoryCard({
  questions,
  onSelectQuestion,
}: PriorSessionMemoryCardProps) {
  if (!questions || questions.length === 0) {
    return null;
  }

  return (
    <div className="mb-6 w-full max-w-xl rounded-2xl border border-cyan-500/30 bg-slate-900/85 p-4.5 backdrop-blur-xl transition-all shadow-[0_0_20px_rgba(56,189,248,0.12)] hover:border-cyan-400/50">
      <div className="flex items-center gap-2 mb-3 text-xs font-bold uppercase tracking-wider text-cyan-300 font-mono">
        <Clock className="h-4 w-4 text-cyan-400" />
        <span>Last time you asked about</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {questions.map((q, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => onSelectQuestion?.(q)}
            className="group flex items-center gap-2 rounded-xl border border-slate-700/80 bg-slate-800/90 px-3.5 py-2 text-xs font-medium text-slate-100 transition-all hover:border-cyan-400/60 hover:bg-cyan-950/40 hover:text-white hover:shadow-[0_0_12px_rgba(56,189,248,0.2)]"
          >
            <Sparkles className="h-3.5 w-3.5 text-cyan-400 opacity-80 group-hover:opacity-100" />
            <span className="truncate max-w-xs">{q}</span>
            <ArrowRight className="h-3.5 w-3.5 text-slate-300 opacity-0 group-hover:opacity-100 transition-opacity" />
          </button>
        ))}
      </div>
    </div>
  );
}
