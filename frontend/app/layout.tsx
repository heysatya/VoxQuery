import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./styles.css";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "VoxQuery",
  description: "Voice-driven data analyst local MVP"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";
  const wrappedChildren = <ErrorBoundary>{children}</ErrorBoundary>;
  const body = authMode === "clerk" ? <ClerkProvider>{wrappedChildren}</ClerkProvider> : wrappedChildren;

  return (
    <html lang="en">
      <body>{body}</body>
    </html>
  );
}

