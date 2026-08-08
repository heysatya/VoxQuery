import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
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

  it("shows a clear/no-flags state and renders 3 fallback KPI takeaway items when there are no anomalies", () => {
    const briefing = makeBriefing({ anomalies: [] });

    render(<MorningBriefingCard token={null} briefing={briefing} variant="drawer" />);

    expect(screen.getByText("Clear")).toBeInTheDocument();
    expect(screen.getByText("Total Revenue (YTD): $4.2M")).toBeInTheDocument();
    expect(screen.getByText("Active Accounts: 1,204")).toBeInTheDocument();
    expect(screen.getByText("Avg Order Value: $118.40")).toBeInTheDocument();
  });

  it("sends the rich follow_up_query (not the bare ranked title) when a flagged anomaly is clicked", () => {
    // Regression test: clicking "Biggest revenue spike" used to send that
    // literal 3-word label as the query, which gives the pipeline no
    // timeframe to anchor on and was observed producing an unaggregated,
    // duplicate-inflated result instead of a real answer. The click must
    // send BriefingAnomaly.follow_up_query instead, which carries the real
    // date/figures the title/description deliberately omit.
    const onSelectInsight = vi.fn();
    const briefing = makeBriefing({
      anomalies: [
        {
          severity: "critical",
          title: "Biggest revenue spike",
          description: "$8,535,126 that period, 240% above the trailing baseline of $2,512,718.",
          direction: "up",
          magnitude_pct: 240,
          follow_up_query:
            "What drove the 240% revenue spike in the week of Nov 06, 2023 (revenue reached " +
            "$8,535,126 vs. a typical $2,512,718)? Show me daily revenue for that week, " +
            "broken down by product category.",
        },
      ],
    });

    render(
      <MorningBriefingCard
        token={null}
        briefing={briefing}
        variant="drawer"
        onSelectInsight={onSelectInsight}
      />
    );

    fireEvent.click(screen.getByText("Biggest revenue spike"));

    expect(onSelectInsight).toHaveBeenCalledTimes(1);
    const sentQuery = onSelectInsight.mock.calls[0][0];
    expect(sentQuery).not.toBe("Biggest revenue spike");
    expect(sentQuery).toContain("Nov 06, 2023");
    expect(sentQuery).toContain("240%");
  });

  it("falls back to the title when an anomaly has no follow_up_query (older producers, e.g. anomaly_detector)", () => {
    const onSelectInsight = vi.fn();
    const briefing = makeBriefing({
      anomalies: [
        {
          severity: "warning",
          title: "Order volume dipped",
          description: "Fewer orders than the trailing baseline this period.",
          // No direction/magnitude_pct/follow_up_query — the older
          // check_turn_anomaly() shape.
        },
      ],
    });

    render(
      <MorningBriefingCard
        token={null}
        briefing={briefing}
        variant="drawer"
        onSelectInsight={onSelectInsight}
      />
    );

    fireEvent.click(screen.getByText("Order volume dipped"));

    expect(onSelectInsight).toHaveBeenCalledWith("Order volume dipped");
  });

  it('opens the full briefing (not a bogus query) when the "+N more" overflow row is clicked', () => {
    const onSelectInsight = vi.fn();
    const onOpenFullBriefing = vi.fn();
    const briefing = makeBriefing({
      anomalies: [1, 2, 3, 4].map((n) => ({
        severity: "warning" as const,
        title: `Anomaly ${n}`,
        description: `Description ${n}`,
        direction: "up" as const,
        magnitude_pct: 10 * n,
        follow_up_query: `Follow-up for anomaly ${n}`,
      })),
    });

    render(
      <MorningBriefingCard
        token={null}
        briefing={briefing}
        variant="drawer"
        onSelectInsight={onSelectInsight}
        onOpenFullBriefing={onOpenFullBriefing}
      />
    );

    fireEvent.click(screen.getByText("+1 more"));

    expect(onOpenFullBriefing).toHaveBeenCalledTimes(1);
    expect(onSelectInsight).not.toHaveBeenCalled();
  });
});
