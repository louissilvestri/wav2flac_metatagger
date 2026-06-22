"use client";

/** First-run hint: until the output folder and FLAC encoder are configured,
 * show a thin banner pointing to Settings. Quiet once everything is set. */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function SetupBanner() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const h = health.data;
  if (!h || h.configured) return null;

  const missing: string[] = [];
  if (!h.output_folder_set) missing.push("an output folder");
  if (!h.flac_available) missing.push("the FLAC encoder path");

  return (
    <div className="mb-2 flex items-center gap-2 rounded-[var(--radius)] border border-accent/40 bg-accent/10 px-3 py-1.5 font-mono text-[0.72rem] text-text">
      <span>Setup needed: configure {missing.join(" and ")} to start converting.</span>
      <Link href="/settings" className="ml-auto shrink-0 text-accent hover:underline">
        Open Settings
      </Link>
    </div>
  );
}
