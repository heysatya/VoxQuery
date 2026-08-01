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
        <div className="flex items-center gap-3.5 mb-2">
          <Image
            src="/brand/voxquery-mark.svg"
            alt=""
            width={48}
            height={48}
            priority
            className="h-10 md:h-12 w-auto object-contain"
          />
          <Image
            src="/brand/voxquery-wordmark.svg"
            alt="VoxQuery"
            width={160}
            height={36}
            priority
            className="h-8 md:h-9 w-auto object-contain"
          />
        </div>
        <p className="text-xs md:text-sm font-medium tracking-wide text-[var(--accent-blue)] uppercase font-mono flex items-center gap-2 mt-1">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)] animate-pulse" />
          {tagline}
        </p>
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
            width={44}
            height={44}
            priority
            className="h-11 w-auto object-contain"
          />
          <Image
            src="/brand/voxquery-wordmark.svg"
            alt="VoxQuery"
            width={150}
            height={32}
            priority
            className="h-8 w-auto object-contain"
          />
        </div>
        <span className="text-xs text-[var(--text-muted)] font-medium">
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
        className="h-6.5 w-auto object-contain"
      />
      <Image
        src="/brand/voxquery-wordmark.svg"
        alt="VoxQuery"
        width={120}
        height={26}
        priority
        className="h-6 w-auto object-contain"
      />
    </Link>
  );
}
