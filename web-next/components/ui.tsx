"use client";

/** Soft Minimalism component library — rounded surfaces, one blue accent,
 * gentle shadows, no glow/chamfer. Every component maps 1:1 to a pattern in
 * the v2 style guide (signature-style.css).
 */

import { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes, RefObject, createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ── Overlay accessibility (shared by Dialog + Drawer) ─────────────────────────
// Per the locked overlay spec: Esc closes, focus moves into the panel and is
// trapped while open, and returns to the trigger on close.
const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

function useOverlayA11y(open: boolean, onClose: () => void, panelRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return;
    const prevFocus = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;

    // Move focus into the overlay (first focusable element, else the panel itself).
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
      if (e.key !== "Tab" || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) { e.preventDefault(); panel.focus(); return; }
      const firstEl = items[0], lastEl = items[items.length - 1];
      if (e.shiftKey && document.activeElement === firstEl) { e.preventDefault(); lastEl.focus(); }
      else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); firstEl.focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      prevFocus?.focus?.();   // restore focus to whatever opened the overlay
    };
  }, [open, onClose, panelRef]);
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function Panel({ title, children, className, actions }: {
  title?: ReactNode; children: ReactNode; className?: string; actions?: ReactNode;
}) {
  return (
    <section
      className={cx(
        "rounded-[var(--radius)] border border-border bg-surface p-4 shadow-[var(--shadow)]",
        className,
      )}
    >
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title && (
            <h2 className="font-display text-lg text-text">{title}</h2>
          )}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

// ── Buttons ───────────────────────────────────────────────────────────────────
// One clear primary (accent fill); everything else recedes. The legacy variant
// names map onto the new language so callers need no churn.

type BtnVariant = "outline" | "solid" | "ghost" | "alert" | "amber";

export function Button({ variant = "outline", className, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant }) {
  const primary = "bg-accent text-accent-ink border-accent hover:brightness-110";
  const variants: Record<BtnVariant, string> = {
    solid: primary,                 // primary action
    amber: primary,                 // legacy "forward" action → also primary
    outline: "bg-transparent text-text border-border hover:border-muted",   // secondary
    ghost: "bg-transparent text-muted border-transparent hover:bg-surface-2 hover:text-text",
    alert: "bg-transparent text-alert border-alert/50 hover:bg-alert/10",    // danger (recedes)
  };
  return (
    <button
      className={cx(
        "cursor-pointer rounded-[var(--radius)] border px-4 py-2 text-xs font-medium",
        "transition-[background,border-color,opacity,filter] duration-[250ms] ease-command",
        "disabled:cursor-not-allowed disabled:opacity-40",
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
      <span className="mb-1 block text-xs text-muted">
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
        "w-full rounded-[var(--radius)] border border-border bg-surface px-3 py-2",
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
        "w-full rounded-[var(--radius)] border border-border bg-surface px-3 py-2",
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
      <input type="checkbox" className="size-4 accent-accent" {...props} />
      {label}
    </label>
  );
}

// ── Badges / chips ────────────────────────────────────────────────────────────

const SOURCE_LABELS: Record<string, string> = {
  musicbrainz: "MB", discogs: "DG", lastfm: "FM", itunes: "IT",
  deezer: "DZ", fanarttv: "FA", acoustid: "AC", coverartarchive: "CAA",
  local: "LOCAL", embedded: "CUR", cue: "CUE",
};

export function SourceChip({ source }: { source: string }) {
  return (
    <span
      title={source}
      className="rounded-full bg-accent/12 px-2 py-px font-mono text-[0.62rem] font-bold text-accent"
    >
      {SOURCE_LABELS[source] ?? source.slice(0, 3).toUpperCase()}
    </span>
  );
}

export function Tag({ tone = "ok", children }: { tone?: "ok" | "warn" | "alert"; children: ReactNode }) {
  // Soft tinted pills (icon/text carries meaning, not colour alone upstream).
  const tones = {
    ok: "text-ok bg-ok/15",
    warn: "text-accent bg-accent/12",
    alert: "text-alert bg-alert/15",
  };
  return (
    <span className={cx("rounded-full px-2 py-px text-[0.7rem] font-medium", tones[tone])}>
      {children}
    </span>
  );
}

export function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={cx("inline-block size-2.5 rounded-full",
        ok ? "bg-ok" : "bg-alert")}
    />
  );
}

// ── Terminal panel ────────────────────────────────────────────────────────────

export type TermLine = { tone?: "ok" | "warn" | "err" | "info"; text: string };

export function Terminal({ lines, busy, className }: {
  lines: TermLine[]; busy?: boolean; className?: string;
}) {
  const tones = {
    ok: "text-ok", warn: "text-accent", err: "text-alert", info: "text-muted",
  };
  return (
    <div className={cx(
      "rounded-[var(--radius)] border border-border bg-surface-2 p-3",
      "font-mono text-[0.78rem] leading-7", className)}>
      {lines.map((l, i) => (
        <div key={i} className={tones[l.tone ?? "info"]}>{l.text}</div>
      ))}
      {busy && <span className="spinner mt-1.5 align-middle" aria-hidden="true" />}
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
        "rounded-[var(--radius)] border bg-surface px-4 py-3 text-left shadow-[var(--shadow)]",
        "transition-[border-color] duration-[250ms] ease-command",
        active ? "border-accent" : "border-border",
        onClick && "cursor-pointer hover:border-accent",
      )}
    >
      <div className="font-display text-2xl text-text">{value}</div>
      <div className="text-xs text-muted">{label}</div>
    </button>
  );
}

// ── Progress bar ──────────────────────────────────────────────────────────────

export function Progress({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
         role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <div
        className="h-full rounded-full bg-accent transition-[width] duration-[250ms] ease-command"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ── Dialog ────────────────────────────────────────────────────────────────────

export function Dialog({ open, title, children, onClose, wide }: {
  open: boolean; title: string; children: ReactNode; onClose: () => void; wide?: boolean;
}) {
  // Portal to <body>: a dialog rendered inside a clip-path/transform ancestor
  // (e.g. a chamfered Panel) gets clipped to that ancestor's box — fixed
  // positioning alone does not escape it.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useRef(`dlg-${Math.random().toString(36).slice(2)}`).current;

  useOverlayA11y(open, onClose, panelRef);

  if (!open || !mounted) return null;
  return createPortal(
    <div
      className="fixed inset-0"
      style={{ zIndex: 9999, background: "color-mix(in oklab, var(--color-bg) 62%, transparent)" }}
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cx(
          "absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
          "max-h-[88vh] overflow-y-auto rounded-[var(--radius)] border border-border bg-surface p-5",
          "shadow-[var(--shadow)] focus:outline-none",
          wide ? "w-[min(94vw,860px)]" : "w-[min(92vw,560px)]",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id={titleId} className="font-display mb-3 text-lg text-text">{title}</h3>
        {children}
      </div>
    </div>,
    document.body,
  );
}

// ── Drawer ────────────────────────────────────────────────────────────────────
// Right-side focused editing surface: a single ordered column with a sticky
// header and footer, so a flow reads top-to-bottom and its primary action is
// always reachable regardless of scroll. Same overlay a11y as Dialog.

export function Drawer({ open, title, subtitle, children, footer, onClose }: {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useRef(`drw-${Math.random().toString(36).slice(2)}`).current;

  useOverlayA11y(open, onClose, panelRef);

  if (!open || !mounted) return null;
  return createPortal(
    <div
      className="fixed inset-0"
      style={{ zIndex: 9999, background: "color-mix(in oklab, var(--color-bg) 62%, transparent)" }}
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="absolute inset-y-0 right-0 flex w-[min(96vw,760px)] flex-col border-l border-border bg-surface shadow-[var(--shadow)] focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h3 id={titleId} className="font-display truncate text-lg text-text">{title}</h3>
            {subtitle && <p className="mt-0.5 truncate text-sm text-muted">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-[var(--radius)] px-2 py-1 text-muted transition-colors hover:bg-surface-2 hover:text-text"
          >
            ✕
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <footer className="shrink-0 border-t border-border bg-surface px-5 py-3">{footer}</footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

// ── Spinner ───────────────────────────────────────────────────────────────────

export function Spinner({ label }: { label?: string }) {
  return (
    <div role="status" aria-live="polite"
         className="flex items-center gap-2 text-sm text-muted">
      <span className="spinner" aria-hidden="true" />
      {label ?? "working…"}
    </div>
  );
}

// ── Toasts ────────────────────────────────────────────────────────────────────
// Transient confirmations (style guide §9): visible system status for every
// commit. The stack lives in an aria-live region; errors announce assertively.

type ToastTone = "ok" | "error" | "info";
type ToastItem = { id: number; tone: ToastTone; title: string; msg?: string };
type PushToast = (t: { tone?: ToastTone; title: string; msg?: string }) => void;

const ToastCtx = createContext<PushToast>(() => {});
export function useToast() { return useContext(ToastCtx); }

export function ToastHost({ children }: { children: ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => setItems((x) => x.filter((i) => i.id !== id)), []);
  const push = useCallback<PushToast>(({ tone = "ok", title, msg }) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, tone, title, msg }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 4000);   // --toast-dur
  }, []);

  const edge = { ok: "border-l-ok", error: "border-l-alert", info: "border-l-accent" };
  const icon = { ok: "✓", error: "!", info: "i" };

  return (
    <ToastCtx.Provider value={push}>
      {children}
      {mounted && createPortal(
        <div className="pointer-events-none fixed bottom-4 right-4 flex flex-col gap-2"
             style={{ zIndex: 10000 }}>
          {items.map((t) => (
            <div
              key={t.id}
              role={t.tone === "error" ? "alert" : "status"}
              aria-live={t.tone === "error" ? "assertive" : "polite"}
              className={cx(
                "pointer-events-auto flex max-w-[340px] items-start gap-2 rounded-[var(--radius)] border border-l-[3px] border-border bg-surface p-3 text-sm shadow-[var(--shadow)]",
                edge[t.tone],
              )}
            >
              <span aria-hidden="true" className="font-bold">{icon[t.tone]}</span>
              <div className="min-w-0">
                <div className="font-medium text-text">{t.title}</div>
                {t.msg && <div className="text-muted">{t.msg}</div>}
              </div>
              <button
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss"
                className="ml-auto shrink-0 text-muted hover:text-text"
              >
                ✕
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  );
}

// ── Pending-changes summary ───────────────────────────────────────────────────
// The always-visible "what will be written" readout for a drawer/footer, so the
// net effect of every upstream toggle is legible at the commit point
// (recognition over recall, NN/g #6).

export function PendingSummary({ fields, tracks, art, className }: {
  fields: number; tracks?: number; art?: string; className?: string;
}) {
  const parts: string[] = [];
  if (fields > 0) parts.push(`${fields} field${fields === 1 ? "" : "s"}`);
  if (tracks && tracks > 0) parts.push(`${tracks} track title${tracks === 1 ? "" : "s"}`);
  if (art) parts.push(`art: ${art}`);
  return (
    <span className={cx("font-mono text-xs text-muted", className)}>
      {parts.length === 0 ? "No changes yet" : `Δ ${parts.join(" · ")}`}
    </span>
  );
}
