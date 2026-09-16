import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { AppShell } from "@/components/layout/app-shell";
import { cn } from "@/lib/utils";

// Referenced by --font-sans in globals.css but never actually loaded before —
// the app was silently falling back to the OS default sans-serif.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "Principal Opportunity Intelligence",
  description: "Find Earlier. Pursue Smarter. Win More. — Business development intelligence for Principal Engineering.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={cn(inter.variable)}>
      <body>
        <AuthProvider>
          <AppShell>{children}</AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
