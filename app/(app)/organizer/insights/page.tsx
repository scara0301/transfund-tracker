"use client";

import { useEffect, useState } from "react";
import { getStoredUser, getCampaigns } from "@/lib/api";
import FraudAlerts from "@/components/FraudAlerts";
import AIInsightsPanel from "@/components/AIInsightsPanel";
import LedgerPanel from "@/components/LedgerPanel";

export default function InsightsPage() {
  const [email, setEmail] = useState<string | null>(null);
  // Read the session after mount so server and client render the same HTML.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setEmail(getStoredUser()?.email ?? null); }, []);
  const [campaigns, setCampaigns] = useState<{ id: number; title: string }[]>([]);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    if (!email) return;
    getCampaigns({ organizer_email: email }).then((c) => { setCampaigns(c); if (c[0]) setSelected(c[0].id); }).catch(() => {});
  }, [email]);

  if (!email) return null;
  return (
    <div className="space-y-6 pb-10 max-w-5xl">
      <div>
        <p className="text-sm text-[#00b964] font-semibold mb-1">AI & Blockchain</p>
        <h1 className="text-2xl font-extrabold text-gray-900">Trust & Safety Center</h1>
        <p className="text-gray-400 text-sm mt-1">Fraud signals across your campaigns, AI spending analysis, and ledger integrity.</p>
      </div>

      <FraudAlerts organizerEmail={email} />

      {campaigns.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="font-extrabold text-gray-900">Expenditure analysis</h2>
            <select value={selected ?? ""} onChange={(e) => setSelected(Number(e.target.value))}
              className="ml-auto border-2 border-gray-100 bg-white px-3 py-2 rounded-xl text-sm focus:outline-none focus:border-[#00b964]">
              {campaigns.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
            </select>
          </div>
          {selected && <AIInsightsPanel campaignId={selected} />}
        </div>
      )}

      <LedgerPanel title="Platform ledger" pageSize={10} />
    </div>
  );
}
