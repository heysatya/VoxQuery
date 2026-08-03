"use client";

import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
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
      className={`fixed top-0 left-0 right-0 z-40 transition-colors duration-300 ${
        scrolled ? "bg-[#090B10]/85 backdrop-blur-xl border-b border-white/[0.06]" : "bg-transparent"
      }`}
    >
      <div className="mx-auto max-w-6xl px-4 md:px-6 h-16 flex items-center justify-between">
        <VoxQueryLogo variant="header" />
        <SignInCTA className="touch-target inline-flex items-center px-4 py-2 rounded-xl text-sm font-semibold text-white bg-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/85 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent-blue)]">
          Sign in
        </SignInCTA>
      </div>
    </motion.header>
  );
}
