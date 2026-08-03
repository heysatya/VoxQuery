"use client";

import React from "react";
import { MotionConfig } from "framer-motion";
import { LandingHeader } from "./LandingHeader";
import { Hero } from "./Hero";
import { LiveDemoPreview } from "./LiveDemoPreview";
import { HowItWorks } from "./HowItWorks";
import { FeatureGrid } from "./FeatureGrid";
import { TrustStrip } from "./TrustStrip";
import { CTASection } from "./CTASection";
import { LandingFooter } from "./LandingFooter";

export function MarketingLandingPage() {
  return (
    <MotionConfig reducedMotion="user">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-50 focus:px-4 focus:py-2 focus:rounded-lg focus:bg-[var(--accent-blue)] focus:text-white focus:text-sm focus:font-semibold"
      >
        Skip to content
      </a>
      <main id="main-content" className="min-h-screen bg-[#090B10] overflow-x-hidden">
        <LandingHeader />
        <Hero />
        <LiveDemoPreview />
        <HowItWorks />
        <FeatureGrid />
        <TrustStrip />
        <CTASection />
        <LandingFooter />
      </main>
    </MotionConfig>
  );
}
