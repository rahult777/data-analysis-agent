import type { Metadata, Viewport } from "next";
import { DM_Sans, Instrument_Serif } from "next/font/google";

import { SITE_NAME, SITE_URL } from "@/lib/site";

import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-display",
  display: "swap",
});

// The site-wide head. The link-preview card (opengraph-image.png and its alt
// text) and the icons come from app/'s file conventions. Pages set no
// openGraph of their own: a page's openGraph replaces this whole object and
// drops the card. Canonical links are set per page: one here would reach every
// page, the 404 included. Local mode has no site address, so Next resolves the
// card against its localhost fallback and warns (accepted: no URL in code).
export const metadata: Metadata = {
  metadataBase: SITE_URL === undefined ? undefined : new URL(SITE_URL),
  title: { default: SITE_NAME, template: `%s · ${SITE_NAME}` },
  description:
    "Four AI agents profile, clean and analyze a spreadsheet, then write one report at three depths, pausing to ask a person about an uncertain domain, missing values and outliers.",
  openGraph: { siteName: SITE_NAME, type: "website", locale: "en_US" },
  twitter: { card: "summary_large_image" },
};

// Dark only (the html element is always "dark"), so native controls,
// scrollbars and the first paint are dark too. The theme color is the dark
// background token (globals.css, .dark --background), oklch(0.145 0 0), in
// sRGB hex: some browsers and link-preview apps don't parse oklch here.
export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#0a0a0a",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`dark ${dmSans.variable} ${instrumentSerif.variable}`}
    >
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
