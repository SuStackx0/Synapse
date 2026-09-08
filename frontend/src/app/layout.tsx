import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Synapse — Codebase Intelligence",
  description: "AI-powered code understanding, graph exploration, and debugging",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-synapse-bg">
        <div className="scanline" />
        {children}
      </body>
    </html>
  );
}
