"use client";

import { useState } from "react";
import { ShieldCheck, ShieldAlert, ShieldX, ChevronDown } from "lucide-react";
import type { RiskSignal } from "@/lib/api";

export function riskLevel(score: number | null | undefined): "low" | "medium" | "high" {
  const s = score ?? 0;
  return s >= 60 ? "high" : s >= 30 ? "medium" : "low";
}

const STYLES = {
  low:    { cls: "bg-green-50 text-green-700 border-green-200", Icon: ShieldCheck, label: "Low risk" },
  medium: { cls: "bg-amber-50 text-amber-700 border-amber-200", Icon: ShieldAlert, label: "Review" },
  high:   { cls: "bg-red-50 text-red-700 border-red-200",       Icon: ShieldX,     label: "High risk" },
};

export default function RiskBadge({ score, compact = false }: { score: number | null | undefined; compact?: boolean }) {
  if (score === null || score === undefined) return null;
  const { cls, Icon, label } = STYLES[riskLevel(score)];
  return (
    <span className={`inline-flex items-center gap-1 border rounded-full font-bold ${compact ? "text-[10px] px-2 py-0.5" : "text-xs px-2.5 py-1"} ${cls}`}
      title={`AI fraud risk score: ${Math.round(score)}/100`}>
      <Icon size={compact ? 10 : 12} />
      {label}{!compact && ` · ${Math.round(score)}`}
    </span>
  );
}

export function RiskSignals({ signals, max = 6 }: { signals: RiskSignal[] | null | undefined; max?: number }) {
  const [open, setOpen] = useState(false);
  if (!signals?.length) return null;
  const shown = open ? signals : signals.slice(0, Math.min(2, max));
  return (
    <div className="mt-2 space-y-1.5">
      {shown.map((s) => (
        <div key={s.code} className="flex items-start gap-2 text-xs">
          <span className={`mt-1 w-1.5 h-1.5 rounded-full shrink-0 ${s.weight >= 0.4 ? "bg-red-500" : s.weight >= 0.2 ? "bg-amber-500" : "bg-gray-400"}`} />
          <span>
            <span className="font-semibold text-gray-700">{s.label}</span>
            {s.detail && <span className="text-gray-400"> — {s.detail}</span>}
          </span>
        </div>
      ))}
      {signals.length > 2 && (
        <button onClick={() => setOpen(!open)} className="text-[11px] font-semibold text-gray-400 hover:text-gray-600 inline-flex items-center gap-1">
          {open ? "Show less" : `+${signals.length - 2} more signal${signals.length - 2 > 1 ? "s" : ""}`}
          <ChevronDown size={11} className={open ? "rotate-180" : ""} />
        </button>
      )}
    </div>
  );
}
