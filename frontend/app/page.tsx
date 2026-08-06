import type { Metadata } from "next";
import React from "react";
import { LandingPageClient } from "./components/landing/LandingPageClient";

export const metadata: Metadata = {
  title: "VoxQuery — Executive answers at the speed of speech!",
  description:
    "VoxQuery turns a spoken question into a warehouse query, a chart, and a narrated answer in seconds - no SQL, no dashboards to build, no waiting on a ticket.",
  openGraph: {
    title: "VoxQuery — Executive answers at the speed of speech!",
    description:
      "Voice-driven data analysis for the warehouse you already have. Speak directly to your data. Bypass the dashboard and accelerate your decisions.",
    images: ["/brand/voxquery-hero.svg"]
  },
  twitter: {
    card: "summary_large_image",
    title: "VoxQuery — Executive answers at the speed of speech!",
    description:
      "Voice-driven data analysis for the warehouse you already have. Speak directly to your data. Bypass the dashboard and accelerate your decisions.",
    images: ["/brand/voxquery-hero.svg"]
  }
};

export default function LandingPage() {
  return <LandingPageClient />;
}
