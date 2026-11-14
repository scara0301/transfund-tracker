

import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "TransFund — Transparent Crowdfunding",
  description:
    "Blockchain and AI-powered transparent crowdfunding and intelligent fund utilization management: secure INR fundraising, a verifiable donation ledger, milestone-based fund release and AI fraud detection.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}