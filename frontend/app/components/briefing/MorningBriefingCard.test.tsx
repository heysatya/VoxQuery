import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MorningBriefingCard } from "./MorningBriefingCard";
import type { ExecutiveBriefingData } from "../../../lib/types";

// token is intentionally null in every test below: the component only
// kicks off its audio-prefetch effect when `token` is truthy, and that
// effect calls `URL.createObjectURL`, which jsdom does not implement.
// Passing `briefing` directly (bypassing the fetch path) plus a null token
// keeps these tests focused on render output with no unrelated network or
// jsdom-shim noise.

function makeBriefing(overrides: Partial<ExecutiveBriefingData> = {}): ExecutiveBriefingData {
  return {
    date: "Wednesday, August 05, 2026",
    greeting: "Good morning",
    kpis: [
      { label: "Total Revenue (YTD)", value: "$4.2M", insight: "Baseline" },
      { label: "Active Accounts", value: "1,204", insight: "Baseline" },
      { label: "Avg Order Value", value: "$118.40", insight: "Baseline" },
      { label: "Total Orders", value: "3,981", insight: "Baseline" },
    ],
    summary_narrative: "Business is steady this week.",
    anomalies: [],
    proactive_insights: [],
    is_live: true,
    data_source: "live",
    ...overrides,
  };
}

describe("MorningBriefingCard", () => {
  it("renders a directional glyph with magnitude % for an anomaly that carries direction/magnitude_pct", () => {
    const briefing = makeBriefing({
      anomalies: [
        {
          severity: "critical",
          title: "Revenue spike — week of Nov 03, 2025",
          description: "$14,627,711 that week, 99% above the trailing baseline of $7,349,121.",
          direction: "up",
          magnitude_pct: 99,
        },
      ],
    });

    render(<MorningBriefingCard token={null} briefing={briefing} variant="drawer" />);

    expect(screen.getByText(/Revenue spike — week of Nov 03, 2025/)).toBeInTheDocument();
    // The SeverityGlyph renders the rounded magnitude as its own text node.
    expect(screen.getByText("99%")).toBeInTheDocument();
  });

  it("falls back to a plain severity dot (no arrow/percent) when direction/magnitude_pct are absent", () => {
    // This is the shape older/other anomaly producers (e.g.
    // anomaly_detector.check_turn_anomaly) emit — direction and
    // magnitude_pct are optional and must not be required for a valid render.
    const briefing = makeBriefing({
      anomalies: [
        {
          severity: "warning",
          title: "Order volume dipped",
          description: "Fewer orders than the trailing baseline this period.",
        },
      ],
    });

    render(<MorningBriefingCard token={null} briefing={briefing} variant="drawer" />);

    expect(screen.getByText("Order volume dipped")).toBeInTheDocument();
    // No magnitude percentage should be rendered anywhere for this anomaly.
    expect(screen.queryByText(/^\d+%$/)).not.toBeInTheDocument();
  });

  it("renders an up-trend badge with the week-over-week % change on a KPI card", () => {
    const briefing = makeBriefing({
      kpis: [
        {
          label: "Total Revenue (YTD)",
          value: "$4.2M",
          change_pct: 50,
          trend: "up",
          insight: "Up 50.0% vs. the prior week.",
        },
        { label: "Active Accounts", value: "1,204", insight: "Baseline" },
        { label: "Avg Order Value", value: "$118.40", insight: "Baseline" },
        { label: "Total Orders", value: "3,981", insight: "Baseline" },
      ],
    });

    render(<MorningBriefingCard token={null} briefing={briefing} variant="drawer" />);

    expect(screen.getByText("+50%")).toBeInTheDocument();
  });

  it("renders a down-trend badge with a negative sign for a declining KPI", () => {
    const briefing = makeBriefing({
      kpis: [
        { label: "Total Revenue (YTD)", value: "$4.2M", insight: "Baseline" },
        { label: "Active Accounts", value: "1,204", insight: "Baseline" },
        { label: "Avg Order Value", value: "$118.40", insight: "Baseline" },
        {
          label: "Total Orders",
          value: "3,981",
          change_pct: -12.5,
          trend: "down",
          insight: "Down 12.5% vs. the prior week.",
        },
      ],
    });

    render(<MorningBriefingCard token={null} briefing={briefing} variant="drawer" />);

    expect(screen.getByText("-12.5%")).toBeInTheDocument();
  });

  it("omits the trend badge entirely when change_pct/trend are null (no WoW data available)", () => {
    const briefing = makeBriefing();

    render(<MorningBriefingCard token={null} briefing={briefing} variant="drawer" />);

    // None of the placeholder KPIs above set change_pct/trend, so no
    // sign-prefixed percentage badge should appear anywhere in the card.
    expect(screen.queryByText(/^[+-]\d/)).not.toBeInTheDocument();
  });

  it("shows a clear/no-flags state when there are no anomalies", () => {
    const briefing = makeBriefing({ anomalies: [] });

    render(<MorningBriefingCard token={null} briefing={briefing} variant="drawer" />);

    expect(screen.getByText("Clear")).toBeInTheDocument();
  });
});
