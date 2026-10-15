import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "E2E Agent Tester — live run", description: "Live view of the agents evaluating a repository" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
