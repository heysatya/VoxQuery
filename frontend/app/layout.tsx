import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "VoxQuery",
  description: "Voice-driven data analyst local MVP"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
