"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { ArrowDown } from "lucide-react";
import { AmbientVoiceOrb } from "./AmbientVoiceOrb";
import { SignInCTA } from "./SignInCTA";

const EXAMPLE_QUESTIONS = [
  "How has monthly revenue trended over time?",
  "Which product categories drive the most revenue?",
  "Which states have the most active customers?",
  "What's our average order value by payment method?"
];

export function Hero() {
  const [questionIndex, setQuestionIndex] = useState(0);
  const prefersReducedMotion = useReducedMotion();

  useEffect(() => {
    if (prefersReducedMotion) return;
    const id = setInterval(() => {
      setQuestionIndex((i) => (i + 1) % EXAMPLE_QUESTIONS.length);
    }, 3200);
    return () => clearInterval(id);
  }, [prefersReducedMotion]);

  const scrollToDemo = () => {
    document.getElementById("demo")?.scrollIntoView({ behavior: prefersReducedMotion ? "auto" : "smooth" });
  };

  return (
    <section className="relative min-h-[100svh] flex flex-col items-center justify-center overflow-hidden px-4 pt-24 pb-16">
      {/* Ambient background blobs, consistent with the app's radial-gradient language */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(ellipse 60% 50% at 20% 15%, rgba(56, 189, 248, 0.10), transparent 60%)," +
            "radial-gradient(ellipse 55% 45% at 85% 20%, rgba(16, 185, 129, 0.08), transparent 60%)," +
            "radial-gradient(ellipse 60% 60% at 50% 100%, rgba(99, 102, 241, 0.08), transparent 60%)"
        }}
      />

      {/* Ambient voice orb, positioned behind the copy */}
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 1.1, ease: [0.23, 1, 0.32, 1] }}
        className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[min(90vw,640px)] aspect-square opacity-70"
      >
        <AmbientVoiceOrb className="w-full h-full" />
      </motion.div>

      <div className="relative z-10 flex flex-col items-center text-center max-w-3xl">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-card-subtle text-xs font-medium text-[var(--text-secondary)] mb-6"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent-green)] animate-pulse" />
          Voice-driven data analysis for the warehouse you already have
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.18 }}
          className="text-4xl md:text-6xl font-bold tracking-tight text-white leading-[1.08]"
        >
          Executive answers
          <br className="hidden sm:block" /> at the speed of speech!
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.28 }}
          className="mt-6 text-base md:text-lg text-[var(--text-secondary)] max-w-xl"
        >
          VoxQuery turns a spoken question into a warehouse query, a chart, and a narrated answer —
          in seconds, with no SQL and no waiting on a ticket.
        </motion.p>

        {/* Rotating example question, framed like a live transcript.
            Decorative/illustrative — hidden from assistive tech, which gets
            a static equivalent instead so nothing is lost and nothing is
            announced on every rotation. */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.36 }}
          className="mt-8 w-full max-w-lg"
        >
          <div aria-hidden="true" className="glass-card px-5 py-4 flex items-center gap-3 text-left">
            <span className="relative flex h-2.5 w-2.5 flex-shrink-0">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--accent-blue)] opacity-60" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-[var(--accent-blue)]" />
            </span>
            <div className="min-h-[1.5rem] flex items-center">
              <AnimatePresence mode="wait">
                <motion.p
                  key={questionIndex}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.4 }}
                  className="text-sm md:text-base text-white font-medium"
                >
                  &ldquo;{EXAMPLE_QUESTIONS[questionIndex]}&rdquo;
                </motion.p>
              </AnimatePresence>
            </div>
          </div>
          <p className="sr-only">
            Example questions you can ask VoxQuery: {EXAMPLE_QUESTIONS.join("; ")}.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.44 }}
          className="mt-10 flex flex-col sm:flex-row items-center gap-4"
        >
          <SignInCTA className="touch-target inline-flex items-center justify-center px-6 py-3.5 rounded-xl text-sm font-semibold text-white bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/85 transition-colors shadow-[0_0_40px_rgba(56,189,248,0.25)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)]">
            Sign in to VoxQuery
          </SignInCTA>
          <button
            type="button"
            onClick={scrollToDemo}
            className="touch-target inline-flex items-center gap-2 px-6 py-3.5 rounded-xl text-sm font-medium text-[var(--text-secondary)] hover:text-white border border-white/10 hover:bg-white/[0.04] transition-colors"
          >
            See it in action
            <ArrowDown className="h-4 w-4" />
          </button>
        </motion.div>
      </div>
    </section>
  );
}
