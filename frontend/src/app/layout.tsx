import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { DemoBanner, SiteHeader } from "@/components/site-header";
import { themeScript } from "@/components/theme-toggle";
import { TooltipProvider } from "@/components/ui/tooltip";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "QuoteDesk: messy emails to draft quotes",
  description:
    "A fine-tuned small model plus a production-style agent harness that turns messy customer emails into draft quotes. Synthetic data, fictional company.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="flex min-h-full flex-col">
        <TooltipProvider>
          <DemoBanner />
          <SiteHeader />
          <main className="flex-1">{children}</main>
          <footer className="border-t py-6 text-center text-xs text-muted-foreground">
            QuoteDesk · portfolio demo · synthetic data, fictional company · student model derived from Gemma (Gemma Terms of Use)
          </footer>
        </TooltipProvider>
      </body>
    </html>
  );
}
