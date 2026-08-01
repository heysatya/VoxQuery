import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VoxQueryLogo } from "./VoxQueryLogo";

describe("VoxQueryLogo component", () => {
  it("renders header variant with accessible alt text and VoxQuery title", () => {
    render(<VoxQueryLogo variant="header" />);
    const logoImg = screen.getByAltText("VoxQuery Icon Mark");
    expect(logoImg).toBeInTheDocument();
    expect(screen.getByText("Vox")).toBeInTheDocument();
    expect(screen.getByText("Query")).toBeInTheDocument();
  });

  it("renders hero variant with tagline", () => {
    render(<VoxQueryLogo variant="hero" />);
    expect(screen.getByAltText("VoxQuery Icon Mark")).toBeInTheDocument();
    expect(screen.getByText(/Voice-Driven Data Analysis/i)).toBeInTheDocument();
  });

  it("renders compact variant", () => {
    render(<VoxQueryLogo variant="compact" />);
    expect(screen.getByAltText("VoxQuery Icon Mark")).toBeInTheDocument();
    expect(screen.getByText("Vox")).toBeInTheDocument();
  });

  it("renders auth variant", () => {
    render(<VoxQueryLogo variant="auth" />);
    expect(screen.getByAltText("VoxQuery Icon Mark")).toBeInTheDocument();
    expect(screen.getByText(/Ambient Voice Analytics/i)).toBeInTheDocument();
  });

  it("renders admin variant with admin badge", () => {
    render(<VoxQueryLogo variant="admin" />);
    expect(screen.getByAltText("VoxQuery Icon Mark")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });
});
