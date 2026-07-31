import { describe, it, expect, vi } from "vitest";
import { triggerPdfExport } from "./pdfExporter";

describe("pdfExporter", () => {
  it("calls window.print when triggered", () => {
    const printMock = vi.fn();
    vi.stubGlobal("print", printMock);

    triggerPdfExport("Test Title", "Test Summary", []);
    expect(printMock).toHaveBeenCalled();
  });
});
