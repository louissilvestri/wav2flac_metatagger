"use client";

/** Cyan Command component library — chamfered panels, glow buttons, terminal.
 * Every component maps 1:1 to a pattern in the style guide.
 */

import { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes } from "react";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function Panel({ title, children, className, actions }: {
  title?: ReactNode; children: ReactNode; className?: string; actions?: ReactNode;
}) {
  return (
    <section
      className={cx(
        "chamfer bg-surface p-4",
        "border border-accent/25",
        className,
      )}
    >
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title && (
            <h2 className="font-display text-accent glow-accent text-base">{title}</h2>
          )}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

// ── Buttons ───────────────────────────────────────────────────────────────────

type BtnVariant = "outline" | "solid" | "ghost" | "alert" | "amber";

export function Button({ variant = "outline", className, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant }) {
  const variants: Record<BtnVariant, string> = {
    outline: "text-accent border-accent hover:box-glow hover:bg-accent/10",
    solid: "bg-accent text-bg border-accent hover:bg-accent/85",
    ghost: "text-muted border-white/15 hover:text-text hover:border-white/30",
    alert: "text-alert border-alert hover:bg-alert/10",
    amber: "bg-accent-2 text-bg border-accent-2 hover:bg-accent-2/85",
  };
  return (
    <button
      className={cx(
        "font-display cursor-pointer rounded-md border px-4 py-1.5 text-[0.78rem]",
        "transition-[box-shadow,opacity,background] duration-[240ms] ease-command",
        "disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}

// ── Form fields ───────────────────────────────────────────────────────────────

export function Field({ label, children, className }: {
  label: string; children: ReactNode; className?: string;
}) {
  return (
    <label className={cx("block", className)}>
      <span className="mb-1 block text-[0.68rem] uppercase tracking-[0.14em] text-muted">
        {label}
      </span>
      {children}
    </label>
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cx(
        "chamfer w-full border border-accent/40 bg-surface px-3 py-1.5",
        "font-mono text-sm text-text placeholder:text-muted/60",
        "focus:border-accent focus:outline-none",
        className,
      )}
      {...props}
    />
  );
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cx(
        "chamfer w-full border border-accent/40 bg-surface px-3 py-1.5",
        "font-mono text-sm text-text focus:border-accent focus:outline-none",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export function Checkbox({ label, ...props }:
  InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm text-text">
      <input type="checkbox" className="size-4 accent-[#22d3ee]" {...props} />
      {label}
    </label>
  );
}

// ── Badges / chips ────────────────────────────────────────────────────────────

const SOURCE_LABELS: Record<string, string> = {
  musicbrainz: "MB", discogs: "DG", lastfm: "FM", itunes: "IT",
  deezer: "DZ", fanarttv: "FA", acoustid: "AC", coverartarchive: "CAA",
  local: "EAC", embedded: "CUR", cue: "CUE",
};

export function SourceChip({ source }: { source: string }) {
  return (
    <span
      title={source}
      className="rounded-sm bg-accent-2 px-1.5 py-px font-mono text-[0.62rem] font-bold text-bg"
    >
      {SOURCE_LABELS[source] ?? source.slice(0, 3).toUpperCase()}
    </span>
  );
}

export function Tag({ tone = "ok", children }: { tone?: "ok" | "warn" | "alert"; children: ReactNode }) {
  const tones = { ok: "bg-ok", warn: "bg-accent-2", alert: "bg-alert" };
  return (
    <span className={cx("rounded-sm px-1.5 font-mono text-[0.7rem] text-bg", tones[tone])}>
      {children}
    </span>
  );
}

export function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={cx("inline-block size-2.5 rounded-full",
        ok ? "bg-ok box-glow-ok" : "bg-alert")}
    />
  );
}

// ── Terminal panel ────────────────────────────────────────────────────────────

export type TermLine = { tone?: "ok" | "warn" | "err" | "info"; text: string };

export function Terminal({ lines, busy, className }: {
  lines: TermLine[]; busy?: boolean; className?: string;
}) {
  const tones = {
    ok: "text-ok", warn: "text-accent-2", err: "text-alert", info: "text-muted",
  };
  return (
    <div className={cx(
      "rounded-md border border-white/10 bg-[#05080b] p-3",
      "font-mono text-[0.78rem] leading-7", className)}>
      {lines.map((l, i) => (
        <div key={i} className={tones[l.tone ?? "info"]}>{l.text}</div>
      ))}
      {busy && <span className="cursor-blink" />}
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

export function StatCard({ label, value, onClick, active }: {
  label: string; value: ReactNode; onClick?: () => void; active?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className={cx(
        "chamfer border bg-surface px-4 py-3 text-left transition-shadow duration-[240ms]",
        active ? "border-accent box-glow" : "border-accent/20",
        onClick && "cursor-pointer hover:box-glow",
      )}
    >
      <div className="font-display text-2xl text-accent glow-accent">{value}</div>
      <div className="text-[0.68rem] uppercase tracking-[0.14em] text-muted">{label}</div>
    </button>
  );
}

// ── Progress bar ──────────────────────────────────────────────────────────────

export function Progress({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="chamfer h-3 w-full border border-accent/30 bg-surface">
      <div
        className="h-full bg-accent transition-[width] duration-[240ms] ease-command"
        style={{ width: `${pct}%`, boxShadow: "var(--glow) var(--color-accent)" }}
      />
    </div>
  );
}

// ── Dialog ────────────────────────────────────────────────────────────────────

export function Dialog({ open, title, children, onClose }: {
  open: boolean; title: string; children: ReactNode; onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-[rgba(2,4,8,0.62)]" onClick={onClose}>
      <div
        className="chamfer absolute left-1/2 top-1/2 w-[min(92vw,560px)] -translate-x-1/2 -translate-y-1/2
                   border border-accent bg-surface p-5 shadow-[0_16px_40px_rgba(0,0,0,0.6)]"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-display mb-3 text-accent glow-accent">{title}</h3>
        {children}
      </div>
    </div>
  );
}

// ── Spinner ───────────────────────────────────────────────────────────────────

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 font-mono text-sm text-muted">
      <span className="cursor-blink" />
      {label ?? "working..."}
    </div>
  );
}
