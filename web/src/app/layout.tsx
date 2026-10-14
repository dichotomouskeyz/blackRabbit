import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "blackRabbit Operator",
  description: "Local research operator console",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
