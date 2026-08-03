"use client";

import React from "react";
import { motion } from "framer-motion";
import { Mic, Network, LineChart } from "lucide-react";
import { SectionHeading } from "./LiveDemoPreview";

const STEPS = [
  {
    icon: Mic,
    step: "01",
    title: "Speak",
    description:
      "Ask in plain language, by voice or text. No SQL, no query builder, no waiting for an analyst."
  },
  {
    icon: Network,
    step: "02",
    title: "Understand",
    description:
      "VoxQuery matches your question against your warehouse schema and asks for clarification if anything's ambiguous, instead of guessing."
  },
  {
    icon: LineChart,
    step: "03",
    title: "Insight",
    description:
      "Get the right chart automatically, plus a spoken narrative that explains what changed and why it matters."
  }
];

export function HowItWorks() {
  return (
    <section className="relative px-4 py-24 md:py-32">
      <div className="mx-auto max-w-5xl">
        <SectionHeading
          eyebrow="How it works"
          title="From a spoken question to a trusted answer"
          description="Three steps, seconds apart — built on real query execution against your warehouse, not a chatbot guessing at numbers."
        />

        <div className="mt-14 grid grid-cols-1 md:grid-cols-3 gap-5">
          {STEPS.map((item, index) => (
            <motion.div
              key={item.step}
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.6, delay: index * 0.12, ease: [0.23, 1, 0.32, 1] }}
              className="glass-card p-6 relative overflow-hidden group hover:border-[var(--border-hover)] transition-colors"
            >
              <span className="absolute -top-2 -right-1 text-6xl font-bold text-white/[0.04] select-none">
                {item.step}
              </span>
              <div className="relative flex items-center justify-center h-11 w-11 rounded-xl bg-[var(--accent-blue)]/10 border border-[var(--accent-blue)]/20 mb-5">
                <item.icon className="h-5 w-5 text-[var(--accent-blue)]" />
              </div>
              <h3 className="relative text-lg font-semibold text-white mb-2">{item.title}</h3>
              <p className="relative text-sm text-[var(--text-secondary)] leading-relaxed">{item.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
