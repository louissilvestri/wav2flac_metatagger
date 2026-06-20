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
    <nav className="flex w-[150px] shrink-0 flex-col gap-0.5 rounded-[var(--radius)] border border-border bg-surface p-2 shadow-[var(--shadow)]">
      <div className="font-display mb-1 border-b border-border px-2 pb-2 pt-1 text-base text-text">
        Music Mgr
      </div>

      {NAV.map((item) => {
        const active = pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cx(
              "rounded-[var(--radius)] px-3 py-2 text-sm",
              "transition-[background,color] duration-[250ms] ease-command",
              active
                ? "bg-surface-2 text-text shadow-[inset_2px_0_0_var(--color-accent)]"
                : "text-muted hover:bg-surface-2 hover:text-text",
            )}
          >
            {item.label}
          </Link>
        );
      })}

      <div className="mt-auto flex items-center gap-2 px-2 pb-1 font-mono text-xs text-muted">
        <StatusDot ok={health.isSuccess} />
        {health.isSuccess ? `v${health.data.version}` : "offline"}
      </div>
    </nav>
  );
}
