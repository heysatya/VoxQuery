"use client";

import React from "react";
import Image from "next/image";

export type VoxQueryLogoVariant = "header" | "hero" | "compact" | "auth" | "admin";

export type VoxQueryLogoProps = {
  variant?: VoxQueryLogoVariant;
  className?: string;
};

export function VoxQueryLogo({ variant = "header", className = "" }: VoxQueryLogoProps) {
  if (variant === "hero") {
    return (
      <div className={`flex flex-col items-center justify-center text-center ${className}`}>
        <div className="flex items-center gap-3.5 mb-2">
          <Image
            src="/brand/voxquery-mark.svg"
            alt="VoxQuery Icon Mark"
            width={64}
            height={64}
            priority
            className="h-14 md:h-16 w-auto object-contain"
          />
          <span className="text-4xl md:text-5xl font-extrabold tracking-tight text-white">
            Vox<span className="text-[var(--accent-blue)]">Query</span>
          </span>
        </div>
        <p className="text-xs md:text-sm font-medium tracking-wide text-[var(--accent-blue)] uppercase font-mono flex items-center gap-2 mt-1">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)] animate-pulse" />
          Voice-Driven Data Analysis
        </p>
      </div>
    );
  }

  if (variant === "compact") {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <Image
          src="/brand/voxquery-mark.svg"
          alt="VoxQuery Icon Mark"
          width={28}
          height={28}
          className="h-6 w-6 object-contain"
        />
        <span className="text-sm font-bold tracking-tight text-white">
          Vox<span className="text-[var(--accent-blue)]">Query</span>
        </span>
      </div>
    );
  }

  if (variant === "auth") {
    return (
      <div className={`flex flex-col items-center justify-center text-center ${className}`}>
        <div className="flex items-center gap-3 mb-2">
          <Image
            src="/brand/voxquery-mark.svg"
            alt="VoxQuery Icon Mark"
            width={52}
            height={52}
            priority
            className="h-12 w-auto object-contain"
          />
          <span className="text-3xl font-extrabold tracking-tight text-white">
            Vox<span className="text-[var(--accent-blue)]">Query</span>
          </span>
        </div>
        <span className="text-xs text-[var(--text-muted)] font-medium">
          Ambient Voice Analytics
        </span>
      </div>
    );
  }

  if (variant === "admin") {
    return (
      <div className={`flex items-center gap-2.5 ${className}`}>
        <Image
          src="/brand/voxquery-mark.svg"
          alt="VoxQuery Icon Mark"
          width={28}
          height={28}
          priority
          className="h-7 w-auto object-contain"
        />
        <div className="flex items-center gap-2 leading-none">
          <span className="text-base font-extrabold tracking-tight text-white">
            Vox<span className="text-[var(--accent-blue)]">Query</span>
          </span>
          <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] border border-[var(--accent-blue)]/30">
            Admin
          </span>
        </div>
      </div>
    );
  }

  // Default: "header"
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <Image
        src="/brand/voxquery-mark.svg"
        alt="VoxQuery Icon Mark"
        width={28}
        height={28}
        priority
        className="h-7 w-auto object-contain"
      />
      <span className="text-base font-extrabold tracking-tight text-white leading-none">
        Vox<span className="text-[var(--accent-blue)]">Query</span>
      </span>
    </div>
  );
}
