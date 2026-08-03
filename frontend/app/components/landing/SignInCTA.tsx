"use client";

import React from "react";
import Link from "next/link";
import { SignInButton } from "@clerk/nextjs";

const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";

type SignInCTAProps = {
  className?: string;
  children: React.ReactNode;
};

/**
 * Renders the given button as a sign-in trigger, adapting to the active auth mode:
 * - "clerk": opens the Clerk sign-in modal, then lands the user on /app.
 * - "fake" (local/dev): no real auth configured, so it's just a link to /app.
 */
export function SignInCTA({ className, children }: SignInCTAProps) {
  if (authMode === "clerk") {
    return (
      <SignInButton mode="modal" forceRedirectUrl="/app">
        <button type="button" className={className}>
          {children}
        </button>
      </SignInButton>
    );
  }

  return (
    <Link href="/app" className={className}>
      {children}
    </Link>
  );
}
