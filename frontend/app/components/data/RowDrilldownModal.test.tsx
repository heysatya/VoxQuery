import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RowDrilldownModal } from "./RowDrilldownModal";

describe("RowDrilldownModal", () => {
  it("renders nothing when isOpen is false", () => {
    const { container } = render(
      <RowDrilldownModal isOpen={false} onClose={() => {}} turnId="t1" />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders loading and content when open", () => {
    // Mock fetch
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve([
            { id: 1, val: "Row A" },
            { id: 2, val: "Row B" },
          ]),
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RowDrilldownModal isOpen={true} onClose={() => {}} turnId="t1" />
    );
    expect(screen.getByText("Raw Transaction Drilldown")).toBeInTheDocument();
  });
});
