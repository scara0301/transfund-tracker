"use client";

import { Plus, Trash2, Wand2 } from "lucide-react";
import { fmtINR } from "@/lib/api";

export type DraftMilestone = { title: string; amount: string; description?: string };

const TEMPLATES = [
  ["Planning & procurement", 0.3],
  ["Execution", 0.5],
  ["Completion & handover", 0.2],
] as const;

export default function MilestoneEditor({ goal, value, onChange, goalLabel = "goal" }: {
  goal: number; value: DraftMilestone[]; onChange: (v: DraftMilestone[]) => void; goalLabel?: string;
}) {
  const total = value.reduce((s, m) => s + (Number(m.amount) || 0), 0);
  const diff = goal - total;
  const set = (i: number, patch: Partial<DraftMilestone>) => onChange(value.map((m, k) => (k === i ? { ...m, ...patch } : m)));

  const autoSplit = () => {
    if (!goal) return;
    let used = 0;
    onChange(TEMPLATES.map(([title, share], i) => {
      const amt = i === TEMPLATES.length - 1 ? goal - used : Math.round(goal * share);
      used += amt;
      return { title, amount: String(amt) };
    }));
  };

  return (
    <div className="space-y-3">
      {value.map((m, i) => (
        <div key={i} className="flex gap-2 items-start">
          <span className="mt-3 w-6 h-6 shrink-0 rounded-full bg-green-100 text-[#00b964] text-xs font-bold flex items-center justify-center">{i + 1}</span>
          <div className="flex-1 grid grid-cols-1 sm:grid-cols-[1fr_140px] gap-2">
            <input value={m.title} onChange={(e) => set(i, { title: e.target.value })} placeholder="e.g. Buy equipment"
              className="border-2 border-gray-100 bg-gray-50 p-2.5 rounded-xl text-sm focus:outline-none focus:border-[#00b964] focus:bg-white" />
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">₹</span>
              <input type="number" min="1" value={m.amount} onChange={(e) => set(i, { amount: e.target.value })} placeholder="Amount"
                className="w-full pl-7 border-2 border-gray-100 bg-gray-50 p-2.5 rounded-xl text-sm focus:outline-none focus:border-[#00b964] focus:bg-white" />
            </div>
            <input value={m.description || ""} onChange={(e) => set(i, { description: e.target.value })} placeholder="What donors should expect to see (optional)"
              className="sm:col-span-2 border-2 border-gray-100 bg-gray-50 p-2.5 rounded-xl text-xs focus:outline-none focus:border-[#00b964] focus:bg-white" />
          </div>
          <button type="button" onClick={() => onChange(value.filter((_, k) => k !== i))} className="mt-2.5 p-1.5 text-gray-300 hover:text-red-500" aria-label="Remove milestone">
            <Trash2 size={16} />
          </button>
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => onChange([...value, { title: "", amount: diff > 0 ? String(diff) : "" }])} disabled={value.length >= 12}
          className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-full border-2 border-gray-100 text-gray-600 hover:border-[#00b964] hover:text-[#00b964] disabled:opacity-40">
          <Plus size={13} /> Add milestone
        </button>
        {goal > 0 && (
          <button type="button" onClick={autoSplit}
            className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-full border-2 border-gray-100 text-gray-600 hover:border-indigo-300 hover:text-indigo-600">
            <Wand2 size={13} /> Suggest 30 / 50 / 20 split
          </button>
        )}
        {value.length > 0 && goal > 0 && (
          <span className={`ml-auto text-xs font-semibold ${diff < 0 ? "text-red-600" : diff === 0 ? "text-green-700" : "text-amber-600"}`}>
            {fmtINR(total)} of {fmtINR(goal)} {goalLabel}
            {diff < 0 ? ` — ${fmtINR(-diff)} over` : diff > 0 ? ` — ${fmtINR(diff)} unallocated` : " ✓"}
          </span>
        )}
      </div>
    </div>
  );
}
