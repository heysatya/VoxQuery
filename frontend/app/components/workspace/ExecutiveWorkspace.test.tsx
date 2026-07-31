import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExecutiveWorkspace } from "./ExecutiveWorkspace";

describe("ExecutiveWorkspace", () => {
  it("renders empty state", () => {
    render(<ExecutiveWorkspace pinnedWidgets={[]} />);
    expect(screen.getByText("No pinned widgets yet.")).toBeInTheDocument();
  });

  it("renders pinned widgets side by side", () => {
    const mockWidgets = [
      {
        id: "w1",
        title: "Total Sales",
        result: {
          turnId: "t1",
          resultData: {
            result: { columns: ["Sales"], rows: [[1000]] },
            warnings: [],
            tts_text: "",
          },
        } as any,
      },
    ];

    render(<ExecutiveWorkspace pinnedWidgets={mockWidgets} />);
    expect(screen.getByText("Total Sales")).toBeInTheDocument();
    expect(screen.getByText("1 rows retrieved")).toBeInTheDocument();
  });
});
