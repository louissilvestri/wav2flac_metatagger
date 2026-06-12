"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cx, StatusDot } from "@/components/ui";

const NAV = [
  { href: "/convert", label: "Convert" },
  { href: "/library", label: "Library" },
  { href: "/history", label: "History" },
  { href: "/settings", label: "Settings" },
];

export function NavRail() {
  const pathname = usePathname();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 30_000,
  });

  return (
    <nav className="flex w-[150px] shrink-0 flex-col gap-1.5 rounded-lg border border-white/10 bg-[#0c1117] p-2">
      <div className="font-display border-b border-white/10 px-1.5 pb-2 pt-1 text-[0.8rem] text-accent glow-accent">
        Music Mgr
      </div>

      {NAV.map((item) => {
        const active = pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cx(
              "font-display chamfer border px-2.5 py-2 text-[0.8rem]",
              "transition-[box-shadow,background] duration-[240ms] ease-command",
              active
                ? "border-accent bg-accent text-bg"
                : "border-accent/30 text-accent hover:box-glow",
            )}
          >
            {item.label}
          </Link>
        );
      })}

      <div className="mt-auto flex items-center gap-2 px-1.5 pb-1 font-mono text-[0.68rem] text-muted">
        <StatusDot ok={health.isSuccess} />
        {health.isSuccess ? `v${health.data.version}` : "offline"}
      </div>
    </nav>
  );
}
