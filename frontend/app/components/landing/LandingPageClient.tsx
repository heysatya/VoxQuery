"use client";

import React, { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import { MarketingLandingPage } from "./MarketingLandingPage";

const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";

export function LandingPageClient() {
  if (authMode === "clerk") return <ClerkLandingPage />;
  return <MarketingLandingPage />;
}

/**
 * Wraps the marketing page with a lightweight redirect: a returning user who
 * is already signed in shouldn't have to click "Sign in" again from the
 * public landing page — send them straight into the workspace at /app.
 * Signed-out visitors (the common case for a marketing page) see the page
 * immediately with no gating or loading flash.
 */
function ClerkLandingPage() {
  const { isLoaded, isSignedIn } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoaded && isSignedIn) {
      router.replace("/app");
    }
  }, [isLoaded, isSignedIn, router]);

  return <MarketingLandingPage />;
}
