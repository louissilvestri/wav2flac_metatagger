import type { Metadata } from "next";
import { Varela_Round, Comfortaa, Fira_Code } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { NavRail } from "@/components/NavRail";
import { SetupBanner } from "@/components/SetupBanner";

// Soft Minimalism type system: Varela Round (display), Comfortaa (body),
// Fira Code (data/mono). Varela Round ships a single 400 weight.
const varela = Varela_Round({
  weight: "400", subsets: ["latin"], variable: "--font-varela",
});
const comfortaa = Comfortaa({
  subsets: ["latin"], variable: "--font-comfortaa",
});
const fira = Fira_Code({
  subsets: ["latin"], variable: "--font-fira",
});

export const metadata: Metadata = {
  title: "Music Manager",
  description: "WAV to FLAC conversion and library management",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${varela.variable} ${comfortaa.variable} ${fira.variable}`}>
      <body className="h-screen overflow-hidden">
        <Providers>
          <div className="flex h-screen gap-2 p-2">
            <NavRail />
            <main className="min-w-0 flex-1 overflow-y-auto pr-1">
              <SetupBanner />
              {children}
            </main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
