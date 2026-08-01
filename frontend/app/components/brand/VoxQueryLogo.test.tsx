import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VoxQueryLogo } from "./VoxQueryLogo";

describe("VoxQueryLogo component", () => {
  it("renders header variant with accessible link and VoxQuery wordmark", () => {
    render(<VoxQueryLogo variant="header" />);
    const link = screen.getByRole("link", { name: /VoxQuery home/i });
    expect(link).toBeInTheDocument();
    expect(screen.getByAltText("VoxQuery")).toBeInTheDocument();
  });

  it("renders hero variant with approved tagline", () => {
    render(<VoxQueryLogo variant="hero" />);
    expect(screen.getByAltText("VoxQuery")).toBeInTheDocument();
    expect(screen.getByText(/Voice-driven data analysis/i)).toBeInTheDocument();
  });

  it("renders compact variant", () => {
    render(<VoxQueryLogo variant="compact" />);
    expect(screen.getByAltText("VoxQuery")).toBeInTheDocument();
  });

  it("renders auth variant with approved tagline", () => {
    render(<VoxQueryLogo variant="auth" />);
    expect(screen.getByAltText("VoxQuery")).toBeInTheDocument();
    expect(screen.getByText(/Voice-driven data analysis/i)).toBeInTheDocument();
  });

  it("renders admin variant with admin badge", () => {
    render(<VoxQueryLogo variant="admin" />);
    expect(screen.getByAltText("VoxQuery")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });
});
