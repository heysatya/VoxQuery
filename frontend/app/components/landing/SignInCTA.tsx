"use client";

import React from "react";
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
 */
export function SignInCTA({ className, children }: SignInCTAProps) {
  if (authMode === "clerk") {
    return (
      <>
        <SignedOut>
          <SignInButton mode="modal">
            <button type="button" className={className}>
              Get Started
            </button>
          </SignInButton>
        </SignedOut>
        <SignedIn>
          <Link href="/app">
            <button type="button" className={className}>
              Enter VoxQuery
            </button>
          </Link>
        </SignedIn>
      </>
    );
  }

  return (
    <Link href="/app" className={className}>
      {children || "Sign in"}
    </Link>
  );
}
