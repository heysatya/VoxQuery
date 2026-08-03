"use client";

import React from "react";
import { motion } from "framer-motion";
import { Database, KeyRound, Building2, ShieldCheck, FileClock } from "lucide-react";

const TRUST_ITEMS = [
  { icon: Database, label: "Snowflake-native queries" },
  { icon: KeyRound, label: "Clerk-based SSO" },
  { icon: Building2, label: "Multi-tenant isolation" },
  { icon: ShieldCheck, label: "Role-based access control" },
  { icon: FileClock, label: "Full audit logging" }
];

export function TrustStrip() {
  return (
    <section className="relative px-4 py-16 border-y border-white/[0.06] bg-white/[0.012]">
      <div className="mx-auto max-w-5xl">
        <motion.p
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="text-center text-xs font-semibold uppercase tracking-[0.2em] text-[var(--text-muted)] mb-8"
        >
          Built for the enterprise data stack
        </motion.p>
        <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-5">
          {TRUST_ITEMS.map((item, index) => (
            <motion.div
              key={item.label}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: index * 0.06 }}
              className="flex items-center gap-2.5 text-sm text-[var(--text-secondary)]"
            >
              <item.icon className="h-4 w-4 text-[var(--text-muted)]" strokeWidth={1.75} />
              <span>{item.label}</span>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
