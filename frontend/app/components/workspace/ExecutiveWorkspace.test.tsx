import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExecutiveWorkspace } from "./ExecutiveWorkspace";
import type { PinnedWidget } from "./ExecutiveWorkspace";

// Mock the API module to prevent real HTTP calls in tests
vi.mock("../../../lib/api", () => ({
  startCheckNow: vi.fn(),
  fetchResult: vi.fn(),
  ApiRequestError: class ApiRequestError extends Error {
    status: number;
    code: string | null;
    constructor(status: number, message: string, code: string | null = null) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
}));

describe("ExecutiveWorkspace", () => {
  it("renders empty state", () => {
    render(<ExecutiveWorkspace pinnedWidgets={[]} />);
    expect(screen.getByText("No findings saved yet")).toBeInTheDocument();
  });

  it("renders saved finding widgets", () => {
    const mockWidgets: PinnedWidget[] = [
      {
        id: "w1",
        title: "Total Sales",
        saved_at: "2026-07-31T00:00:00.000Z",
        chart_type: "bar",
        data_status: "available",
        result: {
          columns: ["month", "sales"],
          rows: [["Jan", 1000]],
          row_count: 1,
          semantic_columns: [
            { name: "sales", display_name: "Sales", role: "metric", value_type: "number", format: "compact number", unit: null },
          ],
        },
      },
    ];

    render(<ExecutiveWorkspace pinnedWidgets={mockWidgets} />);
    expect(screen.getByText("Total Sales")).toBeInTheDocument();
    expect(screen.getByText(/Saved Jul 31, 2026/i)).toBeInTheDocument();
  });
});
