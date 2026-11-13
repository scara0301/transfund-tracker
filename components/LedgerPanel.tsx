"use client";

import { useCallback, useEffect, useState } from "react";
import { getLedger, verifyLedger, getLedgerStatus, shortHash, fmtINR, type LedgerBlock, type LedgerVerification, type LedgerStatus } from "@/lib/api";
import { errMsg } from "@/lib/api";
import { Link2, ShieldCheck, ShieldX, RefreshCw, ChevronDown, Blocks, Copy, Check, Globe } from "lucide-react";

const EVENT_META: Record<string, { label: string; emoji: string; tone: string }> = {
  genesis:                   { label: "Genesis block",       emoji: "🌱", tone: "bg-gray-100 text-gray-600" },
  campaign_created:          { label: "Campaign created",    emoji: "📣", tone: "bg-blue-50 text-blue-700" },
  milestone_plan:            { label: "Milestone plan",      emoji: "🗺️", tone: "bg-indigo-50 text-indigo-700" },
  donation:                  { label: "Donation",            emoji: "💚", tone: "bg-green-50 text-green-700" },
  donation_backfill:         { label: "Donation (imported)", emoji: "💚", tone: "bg-green-50 text-green-700" },
  milestone_proof_submitted: { label: "Proof submitted",     emoji: "📎", tone: "bg-amber-50 text-amber-700" },
  milestone_vote:            { label: "Donor vote",          emoji: "🗳️", tone: "bg-purple-50 text-purple-700" },
  milestone_released:        { label: "Funds released",      emoji: "🔓", tone: "bg-emerald-50 text-emerald-700" },
  milestone_rejected:        { label: "Milestone rejected",  emoji: "⛔", tone: "bg-red-50 text-red-700" },
  expenditure:               { label: "Expenditure",         emoji: "🧾", tone: "bg-orange-50 text-orange-700" },
  utilization_backfill:      { label: "Expense (imported)",  emoji: "🧾", tone: "bg-orange-50 text-orange-700" },
  campaign_closed:           { label: "Campaign closed",     emoji: "🏁", tone: "bg-gray-100 text-gray-700" },
  campaign_deleted:          { label: "Campaign deleted",    emoji: "🗑️", tone: "bg-gray-100 text-gray-700" },
};

function summary(b: LedgerBlock): string {
  const p = b.payload as Record<string, any>;
  const amt = typeof p.amount_paise === "number" ? fmtINR(p.amount_paise / 100) : null;
  switch (b.event_type) {
    case "donation": case "donation_backfill":
      return `${amt} via ${p.payment_method || "payment"}`;
    case "expenditure": case "utilization_backfill":
      return `${amt} · ${p.category} — ${p.description}`;
    case "milestone_vote":
      return `${p.approve ? "Approved" : "Rejected"} with weight ${fmtINR((p.weight_paise ?? 0) / 100)}`;
    case "milestone_released": case "milestone_rejected": case "milestone_proof_submitted":
      return `Milestone #${p.sequence} · ${amt}`;
    case "milestone_plan":
      return `${(p.milestones || []).length} milestones`;
    case "campaign_created":
      return `${p.title} · goal ${fmtINR((p.goal_paise ?? 0) / 100)}`;
    case "campaign_closed":
      return p.reason;
    default:
      return p.purpose || "";
  }
}

function CopyHash({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(value); setDone(true); setTimeout(() => setDone(false), 1200); }}
      className="text-gray-300 hover:text-gray-600 transition" title="Copy">
      {done ? <Check size={12} className="text-green-600" /> : <Copy size={12} />}
    </button>
  );
}

export function VerificationBadge({ v, loading }: { v: LedgerVerification | null; loading?: boolean }) {
  if (loading || !v) return (
    <span className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full bg-gray-100 text-gray-500">
      <RefreshCw size={12} className="animate-spin" /> Verifying ledger…
    </span>
  );
  return v.valid ? (
    <span className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full bg-green-100 text-green-700">
      <ShieldCheck size={13} /> Ledger verified · {v.chain_length} blocks
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full bg-red-100 text-red-700">
      <ShieldX size={13} /> {v.issue_count} integrity issue{v.issue_count !== 1 ? "s" : ""}
    </span>
  );
}

export default function LedgerPanel({ campaignId, title = "Blockchain Ledger", pageSize = 15 }: {
  campaignId?: number; title?: string; pageSize?: number;
}) {
  const [blocks, setBlocks] = useState<LedgerBlock[]>([]);
  const [verification, setVerification] = useState<LedgerVerification | null>(null);
  const [status, setStatus] = useState<LedgerStatus | null>(null);
  const [verifying, setVerifying] = useState(true);
  const [open, setOpen] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");

  const verify = useCallback(async () => {
    setVerifying(true);
    try { setVerification(await verifyLedger(campaignId)); } catch (e: unknown) { setError(errMsg(e)); }
    finally { setVerifying(false); }
  }, [campaignId]);

  useEffect(() => {
    getLedger({ campaign_id: campaignId, limit: pageSize })
      .then((r) => { setBlocks(r.blocks); setHasMore(r.blocks.length === pageSize); })
      .catch((e) => setError(errMsg(e)));
    getLedgerStatus().then(setStatus).catch(() => {});
    verify();
  }, [campaignId, pageSize, verify]);

  const loadMore = async () => {
    const last = blocks[blocks.length - 1];
    if (!last) return;
    const r = await getLedger({ campaign_id: campaignId, limit: pageSize, before: last.index });
    setBlocks((b) => [...b, ...r.blocks]);
    setHasMore(r.blocks.length === pageSize);
  };

  const anchor = verification?.last_anchor;
  const explorer = status?.anchoring.explorer_tx_url;

  return (
    <div className="bg-white rounded-3xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="px-6 py-5 border-b border-gray-50 flex flex-wrap items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-blue-600 text-white flex items-center justify-center">
          <Blocks size={17} />
        </div>
        <div className="flex-1 min-w-[180px]">
          <h3 className="font-extrabold text-gray-900">{title}</h3>
          <p className="text-xs text-gray-400">Every rupee in and out is a SHA-256 hash-chained block. Edit one and the chain breaks.</p>
        </div>
        <VerificationBadge v={verification} loading={verifying} />
        <button onClick={verify} disabled={verifying}
          className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full border-2 border-gray-100 text-gray-600 hover:border-indigo-200 hover:text-indigo-600 transition disabled:opacity-50">
          <RefreshCw size={12} className={verifying ? "animate-spin" : ""} /> Re-verify
        </button>
      </div>

      {/* Anchoring / integrity summary */}
      <div className="px-6 py-3 bg-gray-50/60 border-b border-gray-50 flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-500">
        {verification && <span>Tip: <code className="font-mono text-gray-700">{shortHash(verification.tip_hash, 12)}</code></span>}
        {verification && <span>Proof-of-work: <b className="text-gray-700">{verification.difficulty}</b> leading zeros</span>}
        <span className="inline-flex items-center gap-1">
          <Globe size={12} />
          {anchor ? (
            <>Anchored to <b className="text-gray-700">{anchor.network}</b> up to block #{anchor.to_block}
              {anchor.tx_hash && (explorer
                ? <a className="text-indigo-600 underline ml-1" target="_blank" rel="noreferrer" href={`${explorer}${anchor.tx_hash}`}>view tx</a>
                : <code className="ml-1 font-mono">{shortHash(anchor.tx_hash, 8)}</code>)}
            </>
          ) : status?.anchoring.enabled ? (
            <>Public-chain anchoring on <b className="text-gray-700">{status.anchoring.network}</b> · {status.unanchored_blocks} blocks pending</>
          ) : (
            <>Internal hash chain · public-chain anchoring not configured</>
          )}
        </span>
      </div>

      {verification && !verification.valid && (
        <div className="px-6 py-4 bg-red-50 border-b border-red-100 space-y-1">
          {verification.issues.slice(0, 5).map((i, k) => (
            <p key={k} className="text-xs text-red-700">
              <b>{i.type === "chain" ? `Block #${i.block_index}` : i.type === "drift" ? "Database tampering" : "Unrecorded"}:</b> {i.problems.join("; ")}
            </p>
          ))}
        </div>
      )}

      {error && <p className="px-6 py-4 text-sm text-red-600">{error}</p>}

      {blocks.length === 0 && !error ? (
        <div className="text-center py-12 text-sm text-gray-400">No blocks yet.</div>
      ) : (
        <div className="divide-y divide-gray-50">
          {blocks.map((b) => {
            const meta = EVENT_META[b.event_type] || { label: b.event_type, emoji: "🔗", tone: "bg-gray-100 text-gray-600" };
            const isOpen = open === b.index;
            return (
              <div key={b.index}>
                <button onClick={() => setOpen(isOpen ? null : b.index)}
                  className="w-full px-6 py-3.5 flex items-center gap-3 text-left hover:bg-gray-50/70 transition">
                  <span className="font-mono text-[11px] text-gray-300 w-10 shrink-0">#{b.index}</span>
                  <span className={`text-[11px] font-bold px-2 py-1 rounded-lg shrink-0 ${meta.tone}`}>{meta.emoji} {meta.label}</span>
                  <span className="text-sm text-gray-600 truncate flex-1 min-w-0">{summary(b)}</span>
                  <code className="hidden md:inline font-mono text-[11px] text-gray-400 shrink-0">{shortHash(b.block_hash, 8)}</code>
                  <span className="hidden sm:inline text-[11px] text-gray-300 shrink-0 w-20 text-right">
                    {new Date(b.timestamp).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                  </span>
                  <ChevronDown size={14} className={`text-gray-300 shrink-0 transition ${isOpen ? "rotate-180" : ""}`} />
                </button>
                {isOpen && (
                  <div className="px-6 pb-4 pt-1 bg-gray-50/50 text-xs space-y-1.5">
                    {([["Block hash", b.block_hash], ["Previous hash", b.prev_hash], ["Data hash", b.data_hash]] as const).map(([k, v]) => (
                      <div key={k} className="flex items-center gap-2 min-w-0">
                        <span className="text-gray-400 w-24 shrink-0">{k}</span>
                        <code className="font-mono text-gray-700 truncate">{v}</code>
                        <CopyHash value={v} />
                      </div>
                    ))}
                    <div className="flex gap-2"><span className="text-gray-400 w-24 shrink-0">Nonce</span><code className="font-mono text-gray-700">{b.nonce}</code></div>
                    <div className="flex gap-2"><span className="text-gray-400 w-24 shrink-0">Timestamp</span><code className="font-mono text-gray-700">{b.timestamp}</code></div>
                    <pre className="mt-2 p-3 bg-white border border-gray-100 rounded-xl overflow-x-auto font-mono text-[11px] text-gray-600">{JSON.stringify(b.payload, null, 2)}</pre>
                    <p className="text-[11px] text-gray-400 flex items-center gap-1"><Link2 size={11} /> block_hash = SHA-256(index | timestamp | event_type | data_hash | prev_hash | nonce)</p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {hasMore && (
        <button onClick={loadMore} className="w-full py-3 text-xs font-bold text-gray-400 hover:text-indigo-600 border-t border-gray-50 transition">
          Load older blocks
        </button>
      )}
    </div>
  );
}
