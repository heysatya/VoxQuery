"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { Mic, Volume2 } from "lucide-react";
import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis, Cell } from "recharts";

type DemoStep = "idle" | "listening" | "transcribing" | "thinking" | "answer";

const QUESTION = "How did revenue perform last quarter?";

const CHART_DATA = [
  { name: "Q2", value: 42 },
  { name: "Q3", value: 47 },
  { name: "Q4", value: 44 },
  { name: "Q1", value: 61 }
];

const NARRATION =
  "Revenue reached $61M last quarter, up 39% over Q4 — the strongest quarter this year, led by Enterprise.";

const STEP_DURATIONS: Record<DemoStep, number> = {
  idle: 1400,
  listening: 1800,
  transcribing: 1600,
  thinking: 1300,
  answer: 4200
};

const STEP_ORDER: DemoStep[] = ["idle", "listening", "transcribing", "thinking", "answer"];

export function LiveDemoPreview() {
  const [step, setStep] = useState<DemoStep>("idle");
  const prefersReducedMotion = useReducedMotion();

  useEffect(() => {
    if (prefersReducedMotion) {
      setStep("answer");
      return;
    }
    const currentIndex = STEP_ORDER.indexOf(step);
    const nextStep = STEP_ORDER[(currentIndex + 1) % STEP_ORDER.length];
    const timeout = setTimeout(() => setStep(nextStep), STEP_DURATIONS[step]);
    return () => clearTimeout(timeout);
  }, [step, prefersReducedMotion]);

  return (
    <section id="demo" className="relative px-4 py-24 md:py-32">
      <div className="mx-auto max-w-4xl">
        <SectionHeading
          eyebrow="See it work"
          title="Watch a question become an answer"
          description="No dashboards to build, no SQL to write. Just ask - VoxQuery does the rest, out loud."
        />

        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.7, ease: [0.23, 1, 0.32, 1] }}
          className="mt-12 glass-card overflow-hidden"
        >
          {/* Browser-window chrome for realism */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.06] bg-white/[0.015]">
            <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
            <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
            <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
            <span className="ml-3 text-[11px] text-[var(--text-muted)] font-mono">app.voxquery.ai</span>
          </div>

          <div className="p-6 md:p-10 min-h-[380px] flex flex-col items-center justify-center" aria-hidden="true">
            <AnimatePresence mode="wait">
              {(step === "idle" || step === "listening") && (
                <motion.div
                  key="mic"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.4 }}
                  className="flex flex-col items-center gap-4"
                >
                  <motion.div
                    animate={
                      step === "listening" && !prefersReducedMotion
                        ? { scale: [1, 1.08, 1] }
                        : { scale: 1 }
                    }
                    transition={{ repeat: step === "listening" ? Infinity : 0, duration: 1.4, ease: "easeInOut" }}
                    className={`flex items-center justify-center h-20 w-20 rounded-full transition-colors ${step === "listening"
                        ? "bg-gradient-to-br from-sky-500 via-cyan-500 to-indigo-600 shadow-[0_0_50px_rgba(56,189,248,0.35)]"
                        : "bg-white/5 border border-white/10"
                      }`}
                  >
                    <Mic className="h-8 w-8 text-white" />
                  </motion.div>
                  <p className="text-sm text-[var(--text-muted)]">
                    {step === "listening" ? "Listening..." : "Tap to ask a question"}
                  </p>
                </motion.div>
              )}

              {step === "transcribing" && (
                <motion.div
                  key="transcript"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.4 }}
                  className="w-full max-w-md text-center"
                >
                  <p className="text-xs uppercase tracking-wider text-[var(--text-muted)] mb-3">You asked</p>
                  <TypewriterText text={QUESTION} />
                </motion.div>
              )}

              {step === "thinking" && (
                <motion.div
                  key="thinking"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.4 }}
                  className="flex flex-col items-center gap-3"
                >
                  <div className="flex gap-1.5">
                    {[0, 1, 2].map((i) => (
                      <motion.span
                        key={i}
                        className="h-2 w-2 rounded-full bg-[var(--accent-amber)]"
                        animate={prefersReducedMotion ? {} : { opacity: [0.3, 1, 0.3] }}
                        transition={{ repeat: Infinity, duration: 1, delay: i * 0.15 }}
                      />
                    ))}
                  </div>
                  <p className="text-sm text-[var(--text-muted)]">Querying the warehouse schema...</p>
                </motion.div>
              )}

              {step === "answer" && (
                <motion.div
                  key="answer"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.5 }}
                  className="w-full"
                >
                  <div className="flex items-start gap-3 mb-5">
                    <div className="w-6 h-6 rounded-full bg-gradient-to-br from-[var(--accent-blue)] to-indigo-600 flex-shrink-0 mt-0.5" />
                    <p className="text-sm md:text-base text-white font-medium">{QUESTION}</p>
                  </div>

                  <div className="h-40 mb-5">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={CHART_DATA} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                        <XAxis
                          dataKey="name"
                          axisLine={false}
                          tickLine={false}
                          tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                        />
                        <YAxis hide />
                        <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                          {CHART_DATA.map((entry, index) => (
                            <Cell
                              key={entry.name}
                              fill={index === CHART_DATA.length - 1 ? "var(--accent-blue)" : "rgba(56,189,248,0.35)"}
                            />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>

                  <div className="glass-card-subtle p-4 flex items-start gap-3">
                    <Volume2 className="h-4 w-4 text-[var(--accent-green)] flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{NARRATION}</p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <p className="sr-only">
            Demo: you ask &ldquo;{QUESTION}&rdquo; VoxQuery queries the warehouse and replies, &ldquo;{NARRATION}&rdquo;
          </p>
        </motion.div>
      </div>
    </section>
  );
}

function TypewriterText({ text }: { text: string }) {
  const [visibleChars, setVisibleChars] = useState(0);
  const prefersReducedMotion = useReducedMotion();

  useEffect(() => {
    if (prefersReducedMotion) {
      setVisibleChars(text.length);
      return;
    }
    setVisibleChars(0);
    const id = setInterval(() => {
      setVisibleChars((n) => {
        if (n >= text.length) {
          clearInterval(id);
          return n;
        }
        return n + 1;
      });
    }, 28);
    return () => clearInterval(id);
  }, [text, prefersReducedMotion]);

  return (
    <p className="text-lg md:text-xl text-white font-medium">
      {text.slice(0, visibleChars)}
      <span className="inline-block w-0.5 h-5 bg-[var(--accent-blue)] ml-0.5 align-middle animate-pulse" />
    </p>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  description
}: {
  eyebrow: string;
  title: string;
  description?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.6, ease: [0.23, 1, 0.32, 1] }}
      className="text-center max-w-2xl mx-auto"
    >
      <span className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--accent-blue)]">{eyebrow}</span>
      <h2 className="mt-3 text-3xl md:text-4xl font-bold text-white tracking-tight">{title}</h2>
      {description && <p className="mt-4 text-[var(--text-secondary)] text-base">{description}</p>}
    </motion.div>
  );
}
