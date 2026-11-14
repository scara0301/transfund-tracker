"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getMilestones, submitMilestoneProof, voteMilestone, finalizeMilestone, setMilestonePlan, fmtINR, fmtDate, fileUrl, shortHash,
  type MilestoneState, type Milestone,
} from "@/lib/api";
import { errMsg } from "@/lib/api";
import { Lock, Unlock, Vote, CheckCircle2, XCircle, Clock, Upload, ThumbsUp, ThumbsDown, Paperclip, Flag } from "lucide-react";
import MilestoneEditor, { type DraftMilestone } from "@/components/MilestoneEditor";

const STATUS = {
  pending:  { label: "Locked in escrow", Icon: Lock,         ring: "bg-gray-100 text-gray-400",       pill: "bg-gray-100 text-gray-600" },
  voting:   { label: "Donor vote open",  Icon: Vote,         ring: "bg-amber-100 text-amber-600",     pill: "bg-amber-100 text-amber-700" },
  released: { label: "Released",         Icon: CheckCircle2, ring: "bg-green-100 text-[#00b964]",     pill: "bg-green-100 text-green-700" },
  rejected: { label: "Rejected by donors", Icon: XCircle,    ring: "bg-red-100 text-red-500",         pill: "bg-red-100 text-red-700" },
};

function timeLeft(iso: string | null) {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return "voting closed";
  const h = Math.floor(ms / 3_600_000);
  return h >= 24 ? `${Math.floor(h / 24)}d ${h % 24}h left` : `${h}h ${Math.floor((ms % 3_600_000) / 60_000)}m left`;
}

function VoteBar({ m }: { m: Milestone }) {
  const t = m.tally;
  const total = t.approve_weight + t.reject_weight;
  const ap = total ? (t.approve_weight / total) * 100 : 0;
  return (
    <div className="mt-3">
      <div className="flex h-2.5 rounded-full overflow-hidden bg-gray-100">
        <div className="bg-[#00b964] transition-all" style={{ width: `${ap}%` }} />
        <div className="bg-red-400 transition-all" style={{ width: `${total ? 100 - ap : 0}%` }} />
      </div>
      <div className="flex flex-wrap justify-between gap-2 text-[11px] mt-1.5 text-gray-500">
        <span><b className="text-green-700">{fmtINR(t.approve_weight)}</b> approve ({t.approve_count}) · <b className="text-red-600">{fmtINR(t.reject_weight)}</b> reject ({t.reject_count})</span>
        <span>Turnout {t.turnout_percent}% / {t.quorum_percent}% quorum {t.quorum_met && "✓"}</span>
      </div>
    </div>
  );
}

export default function MilestoneTimeline({ campaignId, mode, userEmail, goal, onChange }: {
  campaignId: number; mode: "donor" | "organizer"; userEmail?: string; goal?: number; onChange?: () => void;
}) {
  const [state, setState] = useState<MilestoneState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [proofFor, setProofFor] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [plan, setPlan] = useState<DraftMilestone[]>([]);

  const load = useCallback(() => {
    getMilestones(campaignId, mode === "donor" ? userEmail : undefined)
      .then(setState).catch((e) => setError(errMsg(e))).finally(() => setLoading(false));
  }, [campaignId, mode, userEmail]);
  useEffect(() => { load(); }, [load]);

  const act = async (id: number, fn: () => Promise<unknown>) => {
    setBusy(id); setError("");
    try { await fn(); load(); onChange?.(); } catch (e: unknown) { setError(errMsg(e)); }
    finally { setBusy(null); }
  };

  const sendProof = (m: Milestone) => act(m.id, async () => {
    const fd = new FormData();
    fd.append("organizer_email", userEmail || "");
    fd.append("note", note);
    if (file) fd.append("proof", file);
    await submitMilestoneProof(m.id, fd);
    setProofFor(null); setNote(""); setFile(null);
  });

  if (loading) return <div className="h-48 bg-white rounded-3xl animate-pulse" />;
  if (!state) return error ? <p className="text-sm text-red-600">{error}</p> : null;
  const { funds, milestones } = state;

  return (
    <div className="bg-white rounded-3xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="px-6 py-5 border-b border-gray-50 flex flex-wrap items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#00b964] to-[#00d4aa] text-white flex items-center justify-center">
          <Flag size={17} />
        </div>
        <div className="flex-1 min-w-[200px]">
          <h3 className="font-extrabold text-gray-900">Milestone Escrow</h3>
          <p className="text-xs text-gray-400">
            Funds unlock tranche by tranche, only after donors approve proof of progress
            ({state.quorum_percent}% quorum or {state.voting_hours}h voting window).
          </p>
        </div>
      </div>

      {/* Funds strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-gray-100">
        {[
          { label: "Raised", value: funds.raised, cls: "text-gray-900" },
          { label: "Locked in escrow", value: funds.locked_in_escrow, cls: "text-indigo-600", Icon: Lock },
          { label: "Released", value: funds.released, cls: "text-[#00b964]", Icon: Unlock },
          { label: "Spent", value: funds.utilized, cls: "text-orange-600" },
        ].map((s) => (
          <div key={s.label} className="bg-white px-5 py-4">
            <p className="text-[11px] text-gray-400 font-semibold uppercase tracking-wide flex items-center gap-1">{s.Icon && <s.Icon size={11} />}{s.label}</p>
            <p className={`text-lg font-extrabold ${s.cls}`}>{fmtINR(s.value)}</p>
          </div>
        ))}
      </div>

      {error && <div className="mx-6 mt-4 bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl px-3 py-2.5">{error}</div>}

      {milestones.length === 0 ? (
        mode === "organizer" ? (
          <div className="p-6">
            <p className="text-sm text-gray-600 mb-1 font-semibold">This campaign has no milestone plan.</p>
            <p className="text-xs text-gray-400 mb-4">All raised funds are currently spendable without donor approval. Add milestones to put remaining funds in escrow — this can only be done before any spending and can&apos;t be changed later.</p>
            <MilestoneEditor goal={goal ?? 0} value={plan} onChange={setPlan} goalLabel="campaign goal" />
            <button disabled={!plan.length || busy === -1}
              onClick={() => act(-1, () => setMilestonePlan(campaignId, userEmail || "", plan.map((p) => ({ title: p.title, amount: Number(p.amount), description: p.description }))))}
              className="mt-4 px-5 py-2.5 rounded-2xl text-sm font-bold text-white disabled:opacity-50"
              style={{ background: "linear-gradient(135deg,#00b964,#00d4aa)" }}>
              Lock milestone plan
            </button>
          </div>
        ) : (
          <div className="p-6 text-sm text-gray-500 flex items-start gap-3">
            <span className="text-2xl">ℹ️</span>
            <p>This campaign doesn&apos;t use milestone escrow — the organizer can spend funds as they arrive. Every expense is still recorded on the blockchain ledger and screened by AI.</p>
          </div>
        )
      ) : (
        <ol className="p-6 space-y-0">
          {milestones.map((m, i) => {
            const st = STATUS[m.status];
            const isNext = m.id === state.next_milestone_id;
            const last = i === milestones.length - 1;
            return (
              <li key={m.id} className="relative flex gap-4">
                {!last && <span className="absolute left-[19px] top-11 bottom-0 w-0.5 bg-gray-100" />}
                <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${st.ring}`}><st.Icon size={18} /></div>
                <div className={`flex-1 min-w-0 ${last ? "" : "pb-7"}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-bold text-gray-900">{m.sequence}. {m.title}</p>
                    <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${st.pill}`}>{st.label}</span>
                    <span className="ml-auto font-extrabold text-gray-800">{fmtINR(m.amount)}</span>
                  </div>
                  {m.description && <p className="text-xs text-gray-400 mt-0.5">{m.description}</p>}

                  {m.proof_note && (
                    <div className="mt-3 p-3 rounded-2xl bg-gray-50 border border-gray-100">
                      <p className="text-xs text-gray-400 font-semibold mb-1">Organizer&apos;s proof {m.submitted_at && `· ${fmtDate(m.submitted_at)}`}</p>
                      <p className="text-sm text-gray-700">{m.proof_note}</p>
                      <div className="flex flex-wrap gap-3 mt-2 text-[11px]">
                        {m.proof_url && <a href={fileUrl(m.proof_url)} target="_blank" rel="noreferrer" className="text-indigo-600 underline inline-flex items-center gap-1"><Paperclip size={11} />View attachment</a>}
                        {m.proof_hash && <span className="text-gray-400 font-mono">sha256 {shortHash(m.proof_hash, 8)}</span>}
                      </div>
                    </div>
                  )}

                  {(m.status === "voting" || (m.status !== "pending" && m.tally.voter_count > 0)) && <VoteBar m={m} />}
                  {m.status === "voting" && <p className="text-[11px] text-amber-600 font-semibold mt-1 inline-flex items-center gap-1"><Clock size={11} />{timeLeft(m.voting_deadline)}</p>}
                  {m.status === "released" && m.released_at && <p className="text-[11px] text-green-700 mt-1">Released {fmtDate(m.released_at)} · block {shortHash(m.ledger_hash, 8)}</p>}

                  {/* Donor actions */}
                  {mode === "donor" && m.status === "voting" && (
                    m.my_vote ? (
                      <p className="mt-3 text-xs font-semibold text-gray-500">You voted to <b className={m.my_vote === "approve" ? "text-green-700" : "text-red-600"}>{m.my_vote}</b> this release.</p>
                    ) : state.my_weight > 0 && !m.tally.window_over ? (
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <button disabled={busy === m.id} onClick={() => act(m.id, () => voteMilestone(m.id, userEmail || "", true))}
                          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-bold text-white bg-[#00b964] hover:bg-[#00a356] disabled:opacity-50"><ThumbsUp size={13} /> Approve release</button>
                        <button disabled={busy === m.id} onClick={() => act(m.id, () => voteMilestone(m.id, userEmail || "", false))}
                          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-bold text-red-600 border-2 border-red-200 hover:bg-red-50 disabled:opacity-50"><ThumbsDown size={13} /> Reject</button>
                        <span className="text-[11px] text-gray-400">Your vote weight: {fmtINR(state.my_weight)}</span>
                      </div>
                    ) : state.my_weight <= 0 ? (
                      <p className="mt-3 text-[11px] text-gray-400">Donate to this campaign to vote on fund releases.</p>
                    ) : null
                  )}

                  {/* Organizer actions */}
                  {mode === "organizer" && isNext && (m.status === "pending" || m.status === "rejected") && (
                    proofFor === m.id ? (
                      <div className="mt-3 p-4 rounded-2xl border-2 border-dashed border-[#00b964]/40 bg-green-50/40 space-y-3">
                        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3}
                          placeholder="What was achieved? Donors read this before voting."
                          className="w-full border-2 border-gray-100 bg-white p-3 rounded-xl text-sm focus:outline-none focus:border-[#00b964]" />
                        <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer">
                          <Upload size={14} /> {file ? file.name : "Attach photo / report (optional)"}
                          <input type="file" className="hidden" accept="image/*,.pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} />
                        </label>
                        <div className="flex gap-2">
                          <button disabled={!note.trim() || busy === m.id} onClick={() => sendProof(m)}
                            className="px-4 py-2 rounded-full text-xs font-bold text-white disabled:opacity-50" style={{ background: "linear-gradient(135deg,#00b964,#00d4aa)" }}>
                            {busy === m.id ? "Submitting…" : "Submit for donor vote"}
                          </button>
                          <button onClick={() => setProofFor(null)} className="px-4 py-2 rounded-full text-xs font-bold text-gray-500 border-2 border-gray-100">Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <button onClick={() => setProofFor(m.id)}
                        className="mt-3 inline-flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-bold text-[#00b964] border-2 border-[#00b964]/30 hover:bg-green-50">
                        <Upload size={13} /> {m.status === "rejected" ? "Resubmit proof" : "Request release — submit proof"}
                      </button>
                    )
                  )}
                  {mode === "organizer" && m.status === "voting" && (
                    <div className="mt-3 flex items-center gap-3">
                      <button disabled={!m.tally.can_finalize || busy === m.id} onClick={() => act(m.id, () => finalizeMilestone(m.id, userEmail || ""))}
                        className="px-4 py-2 rounded-full text-xs font-bold text-white disabled:opacity-40 disabled:cursor-not-allowed"
                        style={{ background: "linear-gradient(135deg,#6366f1,#0069ff)" }}>
                        Close vote {m.tally.can_finalize && (m.tally.passing ? "& release funds" : "(will be rejected)")}
                      </button>
                      {!m.tally.can_finalize && <span className="text-[11px] text-gray-400">Waiting for {m.tally.quorum_percent}% turnout or the deadline.</span>}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
