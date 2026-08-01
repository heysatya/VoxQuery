"use client";

import React, { FormEvent, useId } from "react";
import { Send, Bot, Mic } from "lucide-react";
import { cn } from "../../../lib/utils";
import type { RecordingState } from "../../../lib/types";
import type { UserNotice } from "../../state/interactionState";

type QueryDockProps = {
  value: string;
  disabled: boolean;
  isReady: boolean;
  recordingState: RecordingState;
  notice: UserNotice;
  onChange: (value: string) => void;
  onSubmit: () => void | Promise<void>;
  onFakeVoice: () => void | Promise<void>;
  onToggleRecording?: () => void | Promise<void>;
  onResetConversation: () => void | Promise<void>;
};

export function QueryDock({
  value,
  disabled,
  isReady,
  recordingState,
  notice,
  onChange,
  onSubmit,
  onFakeVoice,
  onToggleRecording,
  onResetConversation
}: QueryDockProps) {
  const id = useId();
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!disabled && value.trim()) onSubmit();
  };
  const noticeColor = {
    info: isReady ? "bg-[var(--accent-green)]" : "bg-[var(--accent-amber)] animate-pulse",
    warning: "bg-[var(--accent-amber)]",
    error: "bg-red-400"
  }[notice.severity];

  return (
    <div className="w-full max-w-2xl mx-auto">
      <form
        onSubmit={handleSubmit}
        className="relative flex items-center w-full glass-card p-1.5 focus-within:border-[var(--accent-blue)]/40 transition-colors"
      >
        <label htmlFor={id} className="sr-only">Ask a data question</label>
        <input
          id={id}
          type="text"
          value={value}
          disabled={disabled || recordingState !== "idle"}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Or type your question here..."
          className="flex-1 px-4 py-2.5 bg-transparent border-none focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-blue)] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] disabled:opacity-50 text-sm"
        />

        <div className="flex items-center pr-1 gap-1">
          <button
            type="button"
            onClick={onResetConversation}
            className="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] rounded-xl transition-colors touch-target flex items-center justify-center"
            title="New conversation"
            aria-label="New conversation"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 21v-5h5"/></svg>
          </button>
          <button
            type="button"
            onClick={onFakeVoice}
            disabled={disabled}
            className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-blue)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] rounded-xl transition-colors disabled:opacity-50 touch-target flex items-center justify-center"
            title="Demo voice"
            aria-label="Demo voice"
          >
            <Bot className="h-4 w-4" />
          </button>
          {onToggleRecording && (
            <button
              type="button"
              onClick={onToggleRecording}
              disabled={disabled && recordingState !== "recording"}
              className={cn(
                "p-2 rounded-xl transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] disabled:opacity-50 touch-target flex items-center justify-center",
                recordingState === "recording"
                  ? "bg-rose-500 text-white animate-pulse"
                  : "text-[var(--text-muted)] hover:text-[var(--accent-blue)]"
              )}
              title={recordingState === "recording" ? "Stop voice input" : "Voice input"}
              aria-label={recordingState === "recording" ? "Stop voice input" : "Voice input"}
            >
              <Mic className="h-4 w-4" />
            </button>
          )}
          <button
            type="submit"
            disabled={disabled || !value.trim()}
            className="p-2.5 text-white bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/80 disabled:bg-slate-800 disabled:text-slate-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)] rounded-xl transition-colors touch-target flex items-center justify-center"
            title="Submit"
            aria-label="Submit"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </form>

      <div className="flex items-center justify-between px-2 mt-2 text-[11px] text-[var(--text-muted)]">
        <div className="flex items-center gap-2" role="status" aria-live="polite">
          <span className={cn(
            "w-1.5 h-1.5 rounded-full",
            noticeColor
          )} />
          <span>{notice.message}</span>
        </div>
      </div>
    </div>
  );
}
