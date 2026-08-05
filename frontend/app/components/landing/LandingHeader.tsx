"use client";

import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity } from "lucide-react";
import Link from "next/link";
import { VoxQueryLogo } from "../brand/VoxQueryLogo";
import { SignInCTA } from "./SignInCTA";

export function LandingHeader() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <motion.header
      initial={{ y: -24, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.5, ease: [0.23, 1, 0.32, 1] }}
      className={`fixed top-0 left-0 right-0 z-40 transition-all duration-300 ${
        scrolled
          ? "bg-[#0A111F]/90 backdrop-blur-xl border-b border-white/[0.08] shadow-[0_4px_30px_rgba(0,0,0,0.5)]"
          : "bg-transparent border-b border-white/[0.04]"
      }`}
    >
      <div className="mx-auto max-w-7xl px-4 md:px-6 h-16 flex items-center justify-between">
        {/* Top Left: Small crisp vector version of VoxQuery logo and text */}
        <div className="flex items-center gap-3">
          <VoxQueryLogo variant="header" />
        </div>

        {/* Top Right: Business pulse indicator & Sign In CTA */}
        <div className="flex items-center gap-3 md:gap-4">
          {/* Business Pulse Indicator Badge */}
          <Link
            href="/app"
            className="px-3.5 py-1.5 rounded-full glass-card border border-[var(--accent-blue)]/30 text-white text-xs font-semibold hover:border-[var(--accent-blue)]/60 hover:shadow-[0_0_15px_rgba(56,189,248,0.2)] transition-all flex items-center gap-2 touch-target"
            aria-label="View Business Pulse"
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--accent-green)] opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-[var(--accent-green)]" />
            </span>
            <span className="hidden sm:inline text-xs font-medium text-slate-200">Business pulse - 3 flags</span>
            <Activity className="h-3.5 w-3.5 text-[var(--accent-green)] sm:hidden" />
          </Link>

          {/* Primary Sign In CTA */}
          <SignInCTA className="touch-target inline-flex items-center px-4 py-2 rounded-xl text-xs md:text-sm font-semibold text-white bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/85 transition-all shadow-[0_0_20px_rgba(56,189,248,0.25)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)]">
            Sign In
          </SignInCTA>
        </div>
      </div>
    </motion.header>
  );
}
