"use client";

import React from "react";
import { VoxQueryLogo } from "../brand/VoxQueryLogo";

export function LandingFooter() {
  const year = new Date().getFullYear();

  return (
    <footer className="relative px-4 py-10 border-t border-white/[0.06]">
      <div className="mx-auto max-w-6xl flex flex-col sm:flex-row items-center justify-between gap-4">
        <VoxQueryLogo variant="compact" />
        <p className="text-xs text-[var(--text-muted)]">© {year} VoxQuery. All rights reserved.</p>
      </div>
    </footer>
  );
}
