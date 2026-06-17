"use client";

/** Side-by-side field comparison with per-field checkboxes, source chips,
 * and alternate-value selection. Used by BOTH the Convert wizard (CUE vs
 * merged providers) and Library Quick Clean Up (current tags vs merged) —
 * one component, no logic drift between tabs.
 */

import { FieldValue } from "@/lib/api";
import { SourceChip, cx } from "@/components/ui";

export interface CompareRow {
  key: string;
  label: string;
  current: string;          // what's in the CUE / file tags now
  merged?: FieldValue;      // aggregated provider value with provenance
}

export interface FieldChoice {
  include: boolean;
  value: string;
  source: string;
}

export type Choices = Record<string, FieldChoice>;

/** Default selection logic, shared everywhere:
 * include when the new value is non-empty AND (current is empty OR new is
 * more specific). A bare year never replaces a full date — the merge engine
 * upstream also guarantees this, belt and braces. */
export function defaultChoices(rows: CompareRow[]): Choices {
  const choices: Choices = {};
  for (const row of rows) {
    const merged = row.merged;
    const value = merged ? asText(merged.value) : "";
    const changed = !!value && value !== row.current;
    const moreSpecific = value.length > row.current.length;
    choices[row.key] = {
      include: changed && (!row.current || moreSpecific),
      value,
      source: merged?.source ?? "",
    };
  }
  return choices;
}

export function asText(v: string | string[]): string {
  return Array.isArray(v) ? v.join("; ") : (v ?? "");
}

export function MetadataCompare({ rows, choices, onChange }: {
  rows: CompareRow[];
  choices: Choices;
  onChange: (choices: Choices) => void;
}) {
  const set = (key: string, patch: Partial<FieldChoice>) =>
    onChange({ ...choices, [key]: { ...choices[key], ...patch } });

  return (
    <table className="w-full border-collapse font-mono text-[0.78rem]">
      <thead>
        <tr className="border-b border-white/15 text-left text-[0.66rem] uppercase tracking-[0.06em] text-muted">
          <th className="w-8 p-1.5" />
          <th className="p-1.5">Field</th>
          <th className="p-1.5">Current</th>
          <th className="p-1.5">New</th>
          <th className="w-20 p-1.5">Source</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const choice = choices[row.key];
          const hasValue = !!choice?.value;
          const changed = hasValue && choice.value !== row.current;
          return (
            <tr key={row.key} className="border-b border-white/5">
              <td className="p-1.5 text-center">
                <input
                  type="checkbox"
                  className="size-3.5 accent-[#22d3ee]"
                  checked={!!choice?.include}
                  onChange={(e) => set(row.key, { include: e.target.checked })}
                />
              </td>
              <td className="whitespace-nowrap p-1.5 font-medium text-text">{row.label}</td>
              <td className="max-w-[220px] truncate p-1.5 text-muted" title={row.current}>
                {row.current || <span className="text-muted/50">—</span>}
              </td>
              <td className={cx("max-w-[220px] truncate p-1.5",
                  !hasValue ? "text-muted/50"
                    : choice?.include ? "text-ok"
                    : "text-muted",
                  changed && choice?.include && "font-medium")}
                  title={choice?.value}>
                {hasValue ? choice.value : <span title="provider had no value">— keep current —</span>}
              </td>
              <td className="p-1.5">
                {hasValue && row.merged && (
                  row.merged.candidates.length > 1 ? (
                    <select
                      className="rounded-sm border border-white/15 bg-surface px-1 py-0.5 text-[0.66rem] text-text"
                      value={choice.source}
                      title="Alternate values from other providers"
                      onChange={(e) => {
                        const cand = row.merged!.candidates.find(c => c.source === e.target.value);
                        if (cand) set(row.key, { value: asText(cand.value), source: cand.source });
                      }}
                    >
                      {row.merged.candidates.map((c) => (
                        <option key={c.source} value={c.source}>
                          {c.source} · {asText(c.value).slice(0, 24)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <SourceChip source={choice.source} />
                  )
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
