"use client";

import { fmtINR, fmtDate, fileUrl, shortHash } from "@/lib/api";
import RiskBadge, { RiskSignals } from "@/components/RiskBadge";
import { FileText, ShieldCheck, Link2 } from "lucide-react";

export type Expense = {
  id: number; amount: number; description: string; category: string; proof_url: string | null;
  created_at: string; milestone_id?: number | null; vendor_name?: string | null; vendor_gstin?: string | null;
  invoice_number?: string | null; invoice_date?: string | null; ocr_total?: number | null;
  risk_score?: number | null; risk_flags?: any[] | null; ledger_hash?: string | null; status?: string | null;
};

export default function ExpenseList({ items, milestoneTitles = {} }: { items: Expense[]; milestoneTitles?: Record<number, string> }) {
  if (!items.length) return (
    <div className="text-center py-14 bg-white rounded-3xl border border-gray-100">
      <div className="text-4xl mb-2">🧾</div>
      <p className="font-bold text-gray-600">No expenses logged yet</p>
      <p className="text-xs text-gray-400 mt-1">Every expense will appear here with its invoice, AI check and ledger hash.</p>
    </div>
  );
  return (
    <div className="space-y-3">
      {items.map((u) => {
        const matched = u.ocr_total && Math.abs(u.amount - u.ocr_total) / u.amount <= 0.05;
        return (
          <div key={u.id} className={`bg-white rounded-2xl border p-5 shadow-sm ${(u.risk_score ?? 0) >= 60 ? "border-red-200" : "border-gray-100"}`}>
            <div className="flex flex-wrap items-start gap-2">
              <p className="font-semibold text-gray-900 flex-1 min-w-[180px]">{u.description}</p>
              <RiskBadge score={u.risk_score} compact />
              <span className="text-[#00b964] font-extrabold">{fmtINR(u.amount)}</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-gray-400 mt-2">
              <span className="capitalize bg-gray-100 text-gray-600 px-2 py-0.5 rounded-md">{u.category}</span>
              <span>{fmtDate(u.created_at)}</span>
              {u.milestone_id && milestoneTitles[u.milestone_id] && <span>🏁 {milestoneTitles[u.milestone_id]}</span>}
              {u.vendor_name && <span>Vendor: <b className="text-gray-600">{u.vendor_name}</b></span>}
              {u.vendor_gstin && <span className="font-mono">{u.vendor_gstin}</span>}
              {u.invoice_number && <span>Inv. {u.invoice_number}</span>}
              {matched && <span className="inline-flex items-center gap-1 text-green-700 font-semibold"><ShieldCheck size={12} />Invoice total verified</span>}
              {u.proof_url && <a href={fileUrl(u.proof_url)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-indigo-600 underline"><FileText size={12} />Invoice</a>}
              {u.ledger_hash && <span className="inline-flex items-center gap-1 font-mono" title={u.ledger_hash}><Link2 size={11} />{shortHash(u.ledger_hash, 8)}</span>}
            </div>
            {(u.risk_score ?? 0) >= 30 && <RiskSignals signals={u.risk_flags} />}
          </div>
        );
      })}
    </div>
  );
}
