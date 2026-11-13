"use client";

import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { getCampaignAnalysis, fmtINR } from "@/lib/api";
import { errMsg } from "@/lib/api";
import { Brain, CheckCircle2, AlertTriangle, Info } from "lucide-react";
import RiskBadge, { RiskSignals } from "@/components/RiskBadge";

const COMPONENT_LABELS: Record<string, [string, number]> = {
  proof_coverage: ["Proof coverage", 30],
  invoice_verification: ["Invoices verified by AI", 20],
  ledger_integrity: ["Ledger integrity", 20],
  milestone_discipline: ["Milestone discipline", 15],
  low_risk: ["Low fraud risk", 15],
};
const GRADE_TONE: Record<string, string> = { A: "text-[#00b964]", B: "text-teal-600", C: "text-amber-600", D: "text-red-600" };

export default function AIInsightsPanel({ campaignId, refreshKey = 0 }: { campaignId: number; refreshKey?: number }) {
  const [a, setA] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getCampaignAnalysis(campaignId).then(setA).catch((e) => setError(errMsg(e)));
  }, [campaignId, refreshKey]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!a) return <div className="h-64 bg-white rounded-3xl animate-pulse" />;
  const t = a.transparency;
  const maxCat = Math.max(1, ...a.categories.map((c: any) => c.amount));

  return (
    <div className="bg-white rounded-3xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="px-6 py-5 border-b border-gray-50 flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 text-white flex items-center justify-center"><Brain size={17} /></div>
        <div className="flex-1">
          <h3 className="font-extrabold text-gray-900">AI Expenditure Analysis</h3>
          <p className="text-xs text-gray-400">Spending patterns, invoice verification and fraud signals, summarised.</p>
        </div>
      </div>

      <div className="p-6 grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-6">
        {/* Transparency score — hero number */}
        <div className="rounded-2xl bg-gray-50 p-5">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Transparency score</p>
          <p className="mt-1 flex items-baseline gap-2">
            <span className="text-5xl font-extrabold text-gray-900">{t.score}</span>
            <span className="text-sm text-gray-400">/ 100</span>
            <span className={`ml-auto text-3xl font-extrabold ${GRADE_TONE[t.grade]}`}>{t.grade}</span>
          </p>
          <div className="mt-4 space-y-2.5">
            {Object.entries(t.components).map(([k, v]) => {
              const [label, max] = COMPONENT_LABELS[k] || [k, 20];
              return (
                <div key={k}>
                  <div className="flex justify-between text-[11px] text-gray-500"><span>{label}</span><span className="font-semibold text-gray-700">{Number(v)} / {max}</span></div>
                  <div className="h-1.5 rounded-full bg-gray-200 mt-1 overflow-hidden">
                    <div className="h-full rounded-full bg-indigo-500" style={{ width: `${(Number(v) / max) * 100}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-4 pt-4 border-t border-gray-200 grid grid-cols-2 gap-3 text-xs">
            <div><p className="text-gray-400">With proof</p><p className="font-bold text-gray-800">{a.proof_coverage}%</p></div>
            <div><p className="text-gray-400">AI-verified</p><p className="font-bold text-gray-800">{a.verified_rate}%</p></div>
            <div><p className="text-gray-400">Avg. risk</p><p className="font-bold text-gray-800">{a.average_risk}</p></div>
            <div><p className="text-gray-400">Burn / month</p><p className="font-bold text-gray-800">{fmtINR(Math.round(a.burn_per_month))}</p></div>
          </div>
        </div>

        <div className="space-y-6 min-w-0">
          {/* Insights */}
          <ul className="space-y-2">
            {a.insights.map((i: any, k: number) => {
              const Icon = i.type === "positive" ? CheckCircle2 : i.type === "warning" ? AlertTriangle : Info;
              const tone = i.type === "positive" ? "text-[#00b964]" : i.type === "warning" ? "text-amber-600" : "text-gray-400";
              return (
                <li key={k} className="flex items-start gap-2 text-sm text-gray-700">
                  <Icon size={15} className={`${tone} shrink-0 mt-0.5`} /><span>{i.text}</span>
                </li>
              );
            })}
          </ul>

          {/* Where the money went */}
          {a.categories.length > 0 && (
            <div>
              <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">Where the money went</p>
              <div className="space-y-2">
                {a.categories.map((c: any) => (
                  <div key={c.category} className="grid grid-cols-[110px_1fr_auto] items-center gap-3 text-sm" title={`${c.count} expense(s)`}>
                    <span className="capitalize text-gray-600 truncate">{c.category}</span>
                    <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full rounded-full bg-[#00b964]" style={{ width: `${(c.amount / maxCat) * 100}%` }} />
                    </div>
                    <span className="text-xs text-gray-700 font-semibold w-28 text-right">{fmtINR(c.amount)} · {c.percent}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Milestone budget vs spent */}
          {a.milestones.length > 0 && (
            <div>
              <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">Milestone budget vs. spent</p>
              <div className="space-y-2.5">
                {a.milestones.map((m: any) => (
                  <div key={m.id} className="text-sm">
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-gray-600">{m.sequence}. {m.title} <span className="text-gray-400 capitalize">· {m.status}</span></span>
                      <span className="text-gray-700 font-semibold">{fmtINR(m.spent)} / {fmtINR(m.budget)}</span>
                    </div>
                    <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${m.spent > m.budget ? "bg-red-500" : "bg-indigo-500"}`} style={{ width: `${Math.min(100, m.percent_spent)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Monthly spend */}
          {a.monthly.length > 1 && (
            <div>
              <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">Monthly spending</p>
              <div className="h-44">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={a.monthly} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke="#f1f5f9" />
                    <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#9ca3af" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} axisLine={false} tickLine={false} width={56}
                      tickFormatter={(v) => (v >= 100000 ? `₹${(v / 100000).toFixed(1)}L` : `₹${Math.round(v / 1000)}k`)} />
                    <Tooltip cursor={{ fill: "#f8fafc" }} formatter={(v) => [fmtINR(Number(v)), "Spent"]} />
                    <Bar dataKey="amount" fill="#00b964" radius={[4, 4, 0, 0]} maxBarSize={36} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Anomalies */}
          {a.anomalies.length > 0 && (
            <div>
              <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">Flagged by fraud detection</p>
              <div className="space-y-2">
                {a.anomalies.map((x: any) => (
                  <div key={x.id} className="p-3 rounded-xl border border-red-100 bg-red-50/40">
                    <div className="flex items-center gap-2 text-sm">
                      <span className="flex-1 font-semibold text-gray-800 truncate">{x.description}</span>
                      <span className="font-bold text-gray-700">{fmtINR(x.amount)}</span>
                      <RiskBadge score={x.risk_score} compact />
                    </div>
                    <RiskSignals signals={x.signals} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
