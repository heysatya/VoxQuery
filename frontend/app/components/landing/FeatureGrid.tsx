"use client";

import React from "react";
import { motion } from "framer-motion";
import { Sunrise, History, Bookmark, TrendingUp, ShieldCheck, AudioLines } from "lucide-react";
import { SectionHeading } from "./LiveDemoPreview";

const FEATURES = [
  {
    icon: Sunrise,
    title: "Executive briefings",
    description: "Start the day with a spoken summary of what moved overnight, before you ask a single question."
  },
  {
    icon: History,
    title: "Conversation memory",
    description: "Ask a follow-up the way you would with an analyst — VoxQuery remembers what you were just looking at."
  },
  {
    icon: Bookmark,
    title: "Saved findings",
    description: "Pin an answer to your workspace and it stays there, chart and narrative included, ready to revisit."
  },
  {
    icon: TrendingUp,
    title: "Anomaly detection",
    description: "Unusual spikes and dips get flagged inline, with a one-tap way to ask what's behind them."
  },
  {
    icon: ShieldCheck,
    title: "Tenant isolation & RBAC",
    description: "Every query runs inside your organization's boundary, with role-based access enforced end to end."
  },
  {
    icon: AudioLines,
    title: "Real voice, not a transcript box",
    description: "Live speech-to-text in, natural spoken narration out — a conversation, not a search bar."
  }
];

export function FeatureGrid() {
  return (
    <section className="relative px-4 py-24 md:py-32">
      <div className="mx-auto max-w-6xl">
        <SectionHeading
          eyebrow="What you get"
          title="Built for the way executives actually work"
          description="Less time waiting on a dashboard request, more time acting on the answer."
        />

        <div className="mt-14 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((feature, index) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.55, delay: (index % 3) * 0.1, ease: [0.23, 1, 0.32, 1] }}
              className="glass-card-subtle p-6 hover:bg-[rgba(16,20,28,0.85)] hover:border-[var(--border-hover)] transition-all"
            >
              <div className="flex items-center justify-center h-10 w-10 rounded-lg bg-white/[0.04] border border-white/[0.06] mb-4">
                <feature.icon className="h-5 w-5 text-[var(--accent-green)]" strokeWidth={1.75} />
              </div>
              <h3 className="text-base font-semibold text-white mb-1.5">{feature.title}</h3>
              <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{feature.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
