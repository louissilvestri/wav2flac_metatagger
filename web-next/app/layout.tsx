import type { Metadata } from "next";
import { Audiowide, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { NavRail } from "@/components/NavRail";

const audiowide = Audiowide({
  weight: "400", subsets: ["latin"], variable: "--font-audiowide",
});
const inter = Inter({
  subsets: ["latin"], variable: "--font-inter",
});
const jetbrains = JetBrains_Mono({
  subsets: ["latin"], variable: "--font-jetbrains",
});

export const metadata: Metadata = {
  title: "Music Manager",
  description: "WAV to FLAC conversion and library management",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${audiowide.variable} ${inter.variable} ${jetbrains.variable}`}>
      <body className="h-screen overflow-hidden">
        <Providers>
          <div className="flex h-screen gap-2 p-2">
            <NavRail />
            <main className="min-w-0 flex-1 overflow-y-auto pr-1">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
