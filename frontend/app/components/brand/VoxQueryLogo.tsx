"use client";

import React from "react";
import Image from "next/image";
import Link from "next/link";

export type VoxQueryLogoVariant = "header" | "hero" | "compact" | "auth" | "admin";

export type VoxQueryLogoProps = {
  variant?: VoxQueryLogoVariant;
  className?: string;
};

export function VoxQueryLogo({ variant = "header", className = "" }: VoxQueryLogoProps) {
  const tagline = "Voice-driven data analysis";

  if (variant === "hero") {
    return (
      <div className={`flex flex-col items-center justify-center text-center ${className}`}>
        <div
          className="relative isolate w-[min(86vw,360px)] aspect-[3/2] overflow-hidden rounded-[28px] bg-[#090B10] shadow-[0_0_70px_rgba(20,184,166,0.13)]"
        >
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(14,116,144,0.20),transparent_68%)]" />
          <Image
            src="/brand/voxquery-hero.png"
            alt="VoxQuery"
            width={2048}
            height={1536}
            priority
            sizes="(max-width: 768px) 86vw, 360px"
            className="absolute left-[-47%] top-[-59%] h-auto w-[189%] max-w-none mix-blend-screen"
          />
          <div className="pointer-events-none absolute inset-0 rounded-[28px] border border-white/[0.06]" />
          <span className="sr-only">{tagline}</span>
        </div>
      </div>
    );
  }

  if (variant === "compact") {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <Image
          src="/brand/voxquery-mark.svg"
          alt=""
          width={24}
          height={24}
          className="h-6 w-6 object-contain"
        />
        <Image
          src="/brand/voxquery-wordmark.svg"
          alt="VoxQuery"
          width={120}
          height={26}
          className="h-5 w-auto object-contain"
        />
      </div>
    );
  }

  if (variant === "auth") {
    return (
      <div className={`flex flex-col items-center justify-center text-center ${className}`}>
        <div className="flex items-center gap-3 mb-2">
          <Image
            src="/brand/voxquery-mark.svg"
            alt=""
            width={56}
            height={56}
            priority
            className="h-14 w-auto object-contain"
          />
          <Image
            src="/brand/voxquery-wordmark.svg"
            alt="VoxQuery"
            width={180}
            height={40}
            priority
            className="h-10 w-auto object-contain"
          />
        </div>
        <span className="text-xs text-[var(--accent-green)] font-medium">
          {tagline}
        </span>
      </div>
    );
  }

  if (variant === "admin") {
    return (
      <div className={`flex items-center gap-2.5 ${className}`}>
        <Image
          src="/brand/voxquery-mark.svg"
          alt=""
          width={28}
          height={28}
          priority
          className="h-7 w-auto object-contain"
        />
        <Image
          src="/brand/voxquery-wordmark.svg"
          alt="VoxQuery"
          width={120}
          height={26}
          priority
          className="h-6 w-auto object-contain"
        />
        <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] border border-[var(--accent-blue)]/30">
          Admin
        </span>
      </div>
    );
  }

  // Default: "header"
  return (
    <Link
      href="/"
      aria-label="VoxQuery home"
      className={`flex items-center gap-2.5 hover:opacity-90 transition-opacity touch-target ${className}`}
    >
      <Image
        src="/brand/voxquery-mark.svg"
        alt=""
        width={26}
        height={26}
        priority
          className="h-7 w-auto object-contain drop-shadow-[0_0_10px_rgba(56,189,248,0.2)]"
      />
      <Image
        src="/brand/voxquery-wordmark.svg"
        alt="VoxQuery"
        width={120}
        height={26}
        priority
          className="h-7 w-auto object-contain"
      />
    </Link>
  );
}
