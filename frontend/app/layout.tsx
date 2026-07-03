import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "./styles.css";

export const metadata: Metadata = {
  title: "VoxQuery",
  description: "Voice-driven data analyst local MVP"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const authMode = process.env.NEXT_PUBLIC_AUTH_MODE ?? "fake";
  const body = authMode === "clerk" ? <ClerkProvider>{children}</ClerkProvider> : children;

  return (
    <html lang="en">
      <body>{body}</body>
    </html>
  );
}
