"use client";

import { useEffect, useState, use } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { getCampaign, getUtilizations, getMilestones, getStoredUser } from "@/lib/api";
import ExpenseList, { type Expense } from "@/components/ExpenseList";
import AIInsightsPanel from "@/components/AIInsightsPanel";
import LedgerPanel from "@/components/LedgerPanel";
import MilestoneTimeline from "@/components/MilestoneTimeline";

export default function Tracking({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const cid = Number(id);
  const [campaign, setCampaign] = useState<any>(null);
  const [utils, setUtils] = useState<Expense[]>([]);
  const [msTitles, setMsTitles] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const user = getStoredUser();

  useEffect(() => {
    Promise.all([getCampaign(cid), getUtilizations(cid), getMilestones(cid)])
      .then(([c, u, m]) => {
        setCampaign(c);
        setUtils(u);
        setMsTitles(Object.fromEntries(m.milestones.map((x) => [x.id, x.title])));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [cid]);

  if (loading) return <div className="p-6 animate-pulse space-y-3">{[1, 2, 3].map((i) => <div key={i} className="h-24 bg-white rounded-3xl" />)}</div>;

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-12">
      <Link href={`/donor/campaign/${id}`} className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-[#00b964] font-medium transition">
        <ArrowLeft size={15} /> Back to campaign
      </Link>

      <div>
        <p className="text-sm text-[#00b964] font-semibold mb-1">Fund tracker</p>
        <h1 className="text-2xl font-extrabold text-gray-900">{campaign?.title}</h1>
        <p className="text-sm text-gray-500 mt-1">Follow every rupee: escrowed milestones, AI-checked invoices, and a tamper-evident ledger you can verify yourself.</p>
      </div>

      <MilestoneTimeline campaignId={cid} mode="donor" userEmail={user?.email} />
      <AIInsightsPanel campaignId={cid} />

      <div>
        <h2 className="font-extrabold text-gray-900 mb-3">Expenses ({utils.length})</h2>
        <ExpenseList items={utils} milestoneTitles={msTitles} />
      </div>

      <LedgerPanel campaignId={cid} title="Campaign ledger" />
    </div>
  );
}
