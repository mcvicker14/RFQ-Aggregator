import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { AppShell } from "@/components/layout/app-shell";

export const metadata: Metadata = {
  title: "Principal Opportunity Intelligence",
  description: "Find Earlier. Pursue Smarter. Win More. — Business development intelligence for Principal Engineering.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <AppShell>{children}</AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
