import type { Metadata } from "next";
import React from "react";
import { LandingPageClient } from "./components/landing/LandingPageClient";

export const metadata: Metadata = {
  title: "VoxQuery — Ask your data warehouse anything, out loud",
  description:
    "VoxQuery turns a spoken question into a warehouse query, a chart, and a narrated answer in seconds — no SQL, no dashboards to build, no waiting on a ticket.",
  openGraph: {
    title: "VoxQuery — Ask your data warehouse anything, out loud",
    description:
      "Voice-driven data analysis for the warehouse you already have. Ask a question, get a chart and a spoken answer in seconds.",
    images: ["/brand/voxquery-hero.png"]
  },
  twitter: {
    card: "summary_large_image",
    title: "VoxQuery — Ask your data warehouse anything, out loud",
    description:
      "Voice-driven data analysis for the warehouse you already have. Ask a question, get a chart and a spoken answer in seconds.",
    images: ["/brand/voxquery-hero.png"]
  }
};

export default function LandingPage() {
  return <LandingPageClient />;
}
