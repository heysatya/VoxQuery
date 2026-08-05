"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { SignedIn, SignedOut, SignInButton } from "@clerk/nextjs";

const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";

type SignInCTAProps = {
  className?: string;
  children?: React.ReactNode;
};

/**
 * Renders the given button as a sign-in trigger, adapting to the active auth mode:
 * - "clerk": conditionally renders based on Clerk state (SignedOut: Get Started modal, SignedIn: Enter VoxQuery link).
 * - "fake" (local/dev): no real auth configured, so it's just a link to /app.
 *
 * Uses mounted state to prevent hydration mismatches between SSR fallback and Clerk client state.
 */
export function SignInCTA({ className, children }: SignInCTAProps) {
  const [mounted, setMounted] = useState(false);
  const label = children || "Sign In";

  useEffect(() => {
    setMounted(true);
  }, []);

  if (authMode === "clerk") {
    if (!mounted) {
      return (
        <Link href="/app" className={className}>
          {label}
        </Link>
      );
    }

    return (
      <>
        <SignedOut>
          <SignInButton
            mode="modal"
            forceRedirectUrl="/app"
            fallbackRedirectUrl="/app"
            signUpForceRedirectUrl="/app"
            signUpFallbackRedirectUrl="/app"
          >
            <button type="button" className={className}>
              {label}
            </button>
          </SignInButton>
        </SignedOut>
        <SignedIn>
          <Link href="/app" className={className}>
            {label}
          </Link>
        </SignedIn>
      </>
    );
  }

  return (
    <Link href="/app" className={className}>
      {label}
    </Link>
  );
}
