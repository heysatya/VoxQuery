"use client";

import React, { FormEvent, useId } from "react";
import { Send, Bot } from "lucide-react";
import { cn } from "../../../lib/utils";
import type { RecordingState } from "../../../lib/types";

type QueryDockProps = {
  value: string;
  disabled: boolean;
  isReady: boolean;
  recordingState: RecordingState;
  notice: string;
  modeLabel: string;
  onChange: (value: string) => void;
  onSubmit: () => void | Promise<void>;
  onFakeVoice: () => void | Promise<void>;
  onResetConversation: () => void | Promise<void>;
};

export function QueryDock({
  value,
  disabled,
  isReady,
  recordingState,
  notice,
  modeLabel,
  onChange,
  onSubmit,
  onFakeVoice,
  onResetConversation
}: QueryDockProps) {
  const id = useId();
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!disabled && value.trim()) onSubmit();
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      <form
        onSubmit={handleSubmit}
        className="relative flex items-center w-full bg-[var(--bg-surface)] rounded-2xl border border-[var(--border)] p-1.5 focus-within:border-[var(--accent-blue)]/30 transition-colors"
      >
        <label htmlFor={id} className="sr-only">Ask a data question</label>
        <input
          id={id}
          type="text"
          value={value}
          disabled={disabled || recordingState !== "idle"}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Or type your question here..."
          className="flex-1 px-4 py-2.5 bg-transparent border-none focus:outline-none text-[var(--text-primary)] placeholder:text-[var(--text-muted)] disabled:opacity-50 text-sm"
        />

        <div className="flex items-center pr-1 gap-1">
          <button
            type="button"
            onClick={onResetConversation}
            className="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded-lg transition-colors"
            title="New conversation"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 21v-5h5"/></svg>
          </button>
          <button
            type="button"
            onClick={onFakeVoice}
            disabled={disabled}
            className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-blue)] rounded-lg transition-colors disabled:opacity-50"
            title="Demo voice"
          >
            <Bot className="h-4 w-4" />
          </button>
          <button
            type="submit"
            disabled={disabled || !value.trim()}
            className="p-2 text-white bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/80 disabled:bg-[var(--text-muted)] rounded-lg transition-colors"
            title="Submit"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </form>

      <div className="flex items-center justify-between px-2 mt-2 text-[11px] text-[var(--text-muted)]">
        <div className="flex items-center gap-2">
          <span className={cn(
            "w-1.5 h-1.5 rounded-full",
            isReady ? "bg-[var(--accent-green)]" : "bg-[var(--accent-amber)] animate-pulse"
          )} />
          <span>{notice}</span>
        </div>
      </div>
    </div>
  );
}
