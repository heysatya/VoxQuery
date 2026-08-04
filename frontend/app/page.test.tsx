import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LandingPage from "./page";

describe("LandingPage", () => {
  it("renders the marketing hero with a headline and sign-in call to action", () => {
    render(<LandingPage />);

    expect(screen.getByRole("heading", { level: 1, name: /executive answers at the speed of speech!/i })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /sign in/i }).length).toBeGreaterThan(0);
  });

  it("has exactly one h1 for correct heading hierarchy", () => {
    render(<LandingPage />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("links every sign-in call to action to /app in fake auth mode", () => {
    render(<LandingPage />);

    const signInLinks = screen.getAllByRole("link", { name: /sign in/i });
    expect(signInLinks.length).toBeGreaterThan(0);
    signInLinks.forEach((link) => {
      expect(link).toHaveAttribute("href", "/app");
    });
  });

  it("renders a skip-to-content link targeting the main landmark", () => {
    render(<LandingPage />);

    const skipLink = screen.getByRole("link", { name: /skip to content/i });
    expect(skipLink).toHaveAttribute("href", "#main-content");
    expect(document.getElementById("main-content")).toBeInTheDocument();
  });

  it("renders the how-it-works steps in order", () => {
    render(<LandingPage />);

    expect(screen.getByRole("heading", { name: "Speak" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Understand" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Insight" })).toBeInTheDocument();
  });

  it("renders the feature grid", () => {
    render(<LandingPage />);

    expect(screen.getByRole("heading", { name: "Executive briefings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Saved findings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Anomaly detection" })).toBeInTheDocument();
  });

  it("renders the footer with the current year", () => {
    render(<LandingPage />);
    const year = new Date().getFullYear().toString();
    expect(screen.getByText(new RegExp(year))).toBeInTheDocument();
  });
});
