import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExecutiveWorkspace } from "./ExecutiveWorkspace";
import type { PinnedWidget } from "./ExecutiveWorkspace";

describe("ExecutiveWorkspace", () => {
  it("renders empty state", () => {
    render(<ExecutiveWorkspace pinnedWidgets={[]} />);
    expect(screen.getByText("No analyses pinned yet")).toBeInTheDocument();
  });

  it("renders pinned widgets side by side", () => {
    const mockWidgets: PinnedWidget[] = [
      {
        id: "w1",
        title: "Total Sales",
        created_at: "2026-07-31T00:00:00.000Z",
        chart_type: "bar",
        result: { columns: ["month", "sales"], rows: [["Jan", 1000]], row_count: 1, semantic_columns: [{ name: "sales", display_name: "Sales", role: "metric", value_type: "number", format: "compact number", unit: null }] },
      },
    ];

    render(<ExecutiveWorkspace pinnedWidgets={mockWidgets} />);
    expect(screen.getByText("Total Sales")).toBeInTheDocument();
    expect(screen.getByText(/Saved Jul 31, 2026/i)).toBeInTheDocument();
  });
});
