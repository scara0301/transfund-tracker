"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getFraudAlerts, fmtINR, fmtDate } from "@/lib/api";
import RiskBadge, { RiskSignals } from "@/components/RiskBadge";
import { ShieldAlert } from "lucide-react";

const KIND = { campaign: "📣 Campaign", donation: "💚 Donation", expense: "🧾 Expense" } as const;

export default function FraudAlerts({ organizerEmail, limit }: { organizerEmail?: string; limit?: number }) {
  const [data, setData] = useState<any>(null);
  const [filter, setFilter] = useState<"all" | "campaign" | "donation" | "expense">("all");
  useEffect(() => { getFraudAlerts(organizerEmail).then(setData).catch(() => setData({ alerts: [], count: 0, high: 0, medium: 0 })); }, [organizerEmail]);

  if (!data) return <div className="h-40 bg-white rounded-3xl animate-pulse" />;
  const items = data.alerts.filter((a: any) => filter === "all" || a.kind === filter).slice(0, limit ?? 200);

  return (
    <div className="bg-white rounded-3xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="px-6 py-5 border-b border-gray-50 flex flex-wrap items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-red-100 text-red-600 flex items-center justify-center"><ShieldAlert size={17} /></div>
        <div className="flex-1 min-w-[180px]">
          <h3 className="font-extrabold text-gray-900">AI Fraud Alerts</h3>
          <p className="text-xs text-gray-400">{data.high} high · {data.medium} need review</p>
        </div>
        <div className="flex gap-1">
          {(["all", "campaign", "donation", "expense"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)}
              className={`text-xs font-bold px-3 py-1.5 rounded-full capitalize transition ${filter === f ? "bg-gray-900 text-white" : "text-gray-500 hover:bg-gray-100"}`}>{f}</button>
          ))}
        </div>
      </div>
      {items.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-4xl mb-2">🛡️</div>
          <p className="font-bold text-gray-600">No risk signals</p>
          <p className="text-xs text-gray-400 mt-1">Campaigns, donations and expenses are screened automatically.</p>
        </div>
      ) : (
        <div className="divide-y divide-gray-50">
          {items.map((a: any) => (
            <div key={`${a.kind}-${a.id}`} className="px-6 py-4">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-[11px] font-bold px-2 py-0.5 rounded-md bg-gray-100 text-gray-600">{KIND[a.kind as keyof typeof KIND]}</span>
                <span className="font-semibold text-gray-800 truncate flex-1 min-w-[140px]">{a.summary}</span>
                <span className="text-xs text-gray-500">{fmtINR(a.amount)}</span>
                <RiskBadge score={a.score} compact />
              </div>
              <p className="text-[11px] text-gray-400 mt-1">
                <Link href={`/organizer/campaigns/${a.campaign_id}`} className="hover:text-[#00b964] underline">{a.campaign_title}</Link> · {fmtDate(a.created_at)}
              </p>
              <RiskSignals signals={a.signals} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
