"use client";

import React from "react";
import { AlertCircle, AlertTriangle, Info, RefreshCw } from "lucide-react";
import { motion } from "framer-motion";
import { cn } from "../../../lib/utils";
import type { NoticeSeverity } from "../../state/interactionState";

type FailureAction = {
  label: string;
  onClick: () => void | Promise<void>;
};

type FailureNoticeProps = {
  severity: NoticeSeverity;
  message: string;
  /** Optional action the user can take to recover. */
  action?: FailureAction;
};

const SEVERITY_STYLES: Record<
  NoticeSeverity,
  { icon: React.ReactNode; bg: string; border: string; text: string }
> = {
  error: {
    icon: <AlertCircle className="h-4 w-4 shrink-0" />,
    bg: "bg-red-500/10",
    border: "border-red-500/25",
    text: "text-red-400",
  },
  warning: {
    icon: <AlertTriangle className="h-4 w-4 shrink-0" />,
    bg: "bg-[var(--accent-amber)]/10",
    border: "border-[var(--accent-amber)]/25",
    text: "text-[var(--accent-amber)]",
  },
  info: {
    icon: <Info className="h-4 w-4 shrink-0" />,
    bg: "bg-[var(--accent-blue)]/8",
    border: "border-[var(--accent-blue)]/20",
    text: "text-[var(--text-secondary)]",
  },
};

/**
 * FailureNotice — structured, severity-aware user notification.
 *
 * Answers three required questions per Phase 3.3:
 * 1. What happened (message).
 * 2. Whether the user's data is safe (implied by severity — errors are local,
 *    never indicate data corruption).
 * 3. What the user can do next (optional action button).
 */
export function FailureNotice({ severity, message, action }: FailureNoticeProps) {
  const styles = SEVERITY_STYLES[severity];

  if (severity === "info" && !action) {
    // Info notices with no action are rendered as the minimal status bar only.
    return null;
  }

  return (
    <motion.div
      role="alert"
      aria-live="assertive"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.25 }}
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3 text-sm",
        styles.bg,
        styles.border,
        styles.text
      )}
    >
      <span className="mt-0.5">{styles.icon}</span>

      <div className="flex-1 min-w-0">
        <p className="leading-snug">{message}</p>
        {severity === "error" && (
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            Your data is safe — this error is local to this request.
          </p>
        )}
      </div>

      {action && (
        <button
          type="button"
          onClick={() => void action.onClick()}
          className={cn(
            "shrink-0 flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)]",
            styles.border,
            "hover:bg-white/5"
          )}
        >
          <RefreshCw className="h-3 w-3" />
          {action.label}
        </button>
      )}
    </motion.div>
  );
}
