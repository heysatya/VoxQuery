"use client";

import React from "react";
import Image from "next/image";

type VoxQueryLogoProps = {
  variant?: "header" | "hero" | "compact";
  className?: string;
};

export function VoxQueryLogo({ variant = "header", className = "" }: VoxQueryLogoProps) {
  if (variant === "hero") {
    return (
      <div className={`flex flex-col items-center justify-center text-center group ${className}`}>
        {/* Glow ambient background halo */}
        <div className="relative flex items-center justify-center mb-4">
          <div className="absolute -inset-1 rounded-2xl bg-gradient-to-r from-sky-500 via-cyan-400 to-emerald-400 opacity-60 blur-xl group-hover:opacity-80 transition duration-500" />
          <div className="relative rounded-2xl overflow-hidden border border-cyan-400/40 bg-slate-950 p-1.5 shadow-[0_0_30px_rgba(56,189,248,0.3)]">
            <Image
              src="/logo.png"
              alt="VoxQuery Logo"
              width={260}
              height={160}
              priority
              className="h-28 w-auto object-contain rounded-xl transition-transform duration-500 group-hover:scale-105"
            />
          </div>
        </div>

        {/* Crisp Gradient Typography */}
        <h1 className="text-3xl md:text-4xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white via-slate-100 to-cyan-200">
          VoxQuery
        </h1>
        <p className="mt-1 text-xs md:text-sm font-medium tracking-wide text-emerald-400 uppercase font-mono flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          Voice-Driven Data Analysis
        </p>
      </div>
    );
  }

  if (variant === "compact") {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <div className="relative rounded-lg overflow-hidden border border-cyan-500/30 bg-slate-950 p-0.5 shadow-[0_0_12px_rgba(56,189,248,0.25)]">
          <Image
            src="/logo.png"
            alt="VoxQuery Logo"
            width={32}
            height={32}
            className="h-6 w-6 object-contain rounded"
          />
        </div>
        <span className="text-sm font-bold tracking-tight text-white">VoxQuery</span>
      </div>
    );
  }

  // Default: "header"
  return (
    <div className={`flex items-center gap-3 px-3 py-1.5 rounded-full bg-slate-900/90 border border-cyan-500/30 shadow-[0_0_20px_rgba(56,189,248,0.2)] backdrop-blur-xl transition-all hover:border-cyan-400/50 ${className}`}>
      <div className="relative rounded-lg overflow-hidden border border-cyan-400/30 bg-slate-950 p-0.5">
        <Image
          src="/logo.png"
          alt="VoxQuery Logo"
          width={40}
          height={24}
          priority
          className="h-6 w-auto object-contain rounded"
        />
      </div>
      <div className="flex flex-col leading-none">
        <span className="text-xs font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white via-sky-100 to-cyan-300">
          VoxQuery
        </span>
        <span className="text-[9px] font-semibold text-emerald-400 font-mono tracking-wider mt-0.5">
          Voice Analyst
        </span>
      </div>
    </div>
  );
}
