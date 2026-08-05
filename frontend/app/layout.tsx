import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { dark } from "@clerk/themes";
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
  const body =
    authMode === "clerk" ? (
      <ClerkProvider
        signInForceRedirectUrl="/app"
        signUpForceRedirectUrl="/app"
        signInFallbackRedirectUrl="/app"
        signUpFallbackRedirectUrl="/app"
        appearance={{
          baseTheme: dark,
          variables: {
            colorPrimary: "#38BDF8",
            colorBackground: "#10141C",
            colorText: "#F8FAFC",
            colorTextSecondary: "#CBD5E1",
            colorInputBackground: "#171D28",
            colorInputText: "#F8FAFC"
          }
        }}
      >
        {wrappedChildren}
      </ClerkProvider>
    ) : (
      wrappedChildren
    );

  return (
    <html lang="en">
      <body>{body}</body>
    </html>
  );
}
