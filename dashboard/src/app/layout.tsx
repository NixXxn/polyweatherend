import type { Metadata, Viewport } from "next";
import { DM_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

const display = DM_Sans({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const mono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "WeatherBuyEnd",
  description: "Mobile ops for METAR NO-eliminated trading",
  applicationName: "WeatherBuyEnd",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "WeatherBuyEnd",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  themeColor: "#eef2f1",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${display.variable} ${mono.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
