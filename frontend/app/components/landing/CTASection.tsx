"use client";

import React from "react";
import { motion } from "framer-motion";
import { SignInCTA } from "./SignInCTA";

export function CTASection() {
  return (
    <section className="relative px-4 py-24 md:py-32 overflow-hidden">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(ellipse 70% 60% at 50% 50%, rgba(56, 189, 248, 0.10), transparent 65%)"
        }}
      />
      <motion.div
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-80px" }}
        transition={{ duration: 0.7, ease: [0.23, 1, 0.32, 1] }}
        className="relative mx-auto max-w-2xl text-center"
      >
        <h2 className="text-3xl md:text-4xl font-bold text-white tracking-tight">
          Your data warehouse is ready to answer. Are you?
        </h2>
        <p className="mt-4 text-[var(--text-secondary)] text-base">
          Sign in and ask your first question in under a minute.
        </p>
        <div className="mt-8 flex justify-center">
          <SignInCTA className="touch-target inline-flex items-center justify-center px-7 py-3.5 rounded-xl text-sm font-semibold text-white bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/85 transition-colors shadow-[0_0_40px_rgba(56,189,248,0.25)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)]">
            Sign In
          </SignInCTA>
        </div>
      </motion.div>
    </section>
  );
}
