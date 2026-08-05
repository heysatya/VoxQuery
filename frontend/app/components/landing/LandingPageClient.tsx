"use client";

import React from "react";
import { MarketingLandingPage } from "./MarketingLandingPage";

/**
 * LandingPageClient renders the marketing landing page for all visitors.
 * Sign-in CTA buttons allow users to explicitly navigate to the workspace at /app
 * or sign in via Clerk.
 */
export function LandingPageClient() {
  return <MarketingLandingPage />;
}
