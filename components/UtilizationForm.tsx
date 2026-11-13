"use client";

import { useState } from "react";
import { scanInvoice, createUtilization, fmtINR, type InvoiceScan, type Milestone } from "@/lib/api";
import { errMsg } from "@/lib/api";
import { ScanLine, FileText, Sparkles, AlertTriangle, CheckCircle2, X, Receipt } from "lucide-react";
import RiskBadge, { RiskSignals } from "@/components/RiskBadge";

export const EXPENSE_CATEGORIES = [
  "medical", "education", "food", "infrastructure", "equipment", "logistics", "salaries", "administrative", "general",
];

const field = "w-full border-2 border-gray-100 bg-gray-50 p-2.5 rounded-xl text-sm focus:outline-none focus:border-[#00b964] focus:bg-white transition";

export default function UtilizationForm({ campaignId, organizerEmail, milestones, spendable, onCreated }: {
  campaignId: number; organizerEmail: string; milestones: Milestone[]; spendable: number; onCreated?: () => void;
}) {
  const released = milestones.filter((m) => m.status === "released");
  const [file, setFile] = useState<File | null>(null);
  const [scan, setScan] = useState<InvoiceScan | null>(null);
  const [scanning, setScanning] = useState(false);
  const [form, setForm] = useState({
    amount: "", description: "", category: "general", milestone_id: released.at(-1)?.id ? String(released.at(-1)!.id) : "",
    vendor_name: "", vendor_gstin: "", invoice_number: "", invoice_date: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<any>(null);
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const onFile = async (f: File | null) => {
    setFile(f); setScan(null); setError("");
    if (!f) return;
    setScanning(true);
    try {
      const s = await scanInvoice(f);
      setScan(s);
      setForm((cur) => ({
        ...cur,
        amount: s.total_amount ? String(s.total_amount) : cur.amount,
        vendor_name: s.vendor_name || cur.vendor_name,
        vendor_gstin: s.vendor_gstin || cur.vendor_gstin,
        invoice_number: s.invoice_number || cur.invoice_number,
        invoice_date: s.invoice_date || cur.invoice_date,
      }));
    } catch (e: unknown) {
      setError(`Couldn't scan the invoice: ${errMsg(e)}. You can still fill the details manually.`);
    } finally {
      setScanning(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const amt = Number(form.amount);
    if (!amt || amt <= 0) return setError("Enter the amount spent");
    if (!form.description.trim()) return setError("Describe what the money was spent on");
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("campaign_id", String(campaignId));
      fd.append("created_by", organizerEmail);
      Object.entries(form).forEach(([k, v]) => v && fd.append(k, v));
      if (file) fd.append("proof", file);
      const r = await createUtilization(fd);
      setResult(r);
      setFile(null); setScan(null);
      setForm((f) => ({ ...f, amount: "", description: "", vendor_name: "", vendor_gstin: "", invoice_number: "", invoice_date: "" }));
      onCreated?.();
    } catch (err: unknown) {
      setError(errMsg(err));
    } finally {
      setSubmitting(false);
    }
  };

  const mismatch = scan?.total_amount && Number(form.amount) && Math.abs(Number(form.amount) - scan.total_amount) / Number(form.amount) > 0.05;

  return (
    <div className="bg-white rounded-3xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="h-1.5" style={{ background: "linear-gradient(90deg,#f97316,#f59e0b,#00b964)" }} />
      <div className="px-6 py-5 border-b border-gray-50 flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-orange-100 text-orange-600 flex items-center justify-center"><Receipt size={17} /></div>
        <div className="flex-1">
          <h3 className="font-extrabold text-gray-900">Log an Expense</h3>
          <p className="text-xs text-gray-400">Upload the invoice — AI reads it, checks it for fraud, and the expense is written to the ledger.</p>
        </div>
        <span className="text-xs font-bold px-3 py-1.5 rounded-full bg-green-50 text-green-700">Spendable {fmtINR(spendable)}</span>
      </div>

      {result && (
        <div className={`mx-6 mt-5 p-4 rounded-2xl border ${result.risk_score >= 60 ? "bg-red-50 border-red-200" : result.risk_score >= 30 ? "bg-amber-50 border-amber-200" : "bg-green-50 border-green-200"}`}>
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} className="text-green-600" />
            <p className="text-sm font-bold text-gray-800 flex-1">Expense of {fmtINR(result.amount)} recorded on the ledger</p>
            <RiskBadge score={result.risk_score} />
            <button onClick={() => setResult(null)} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
          </div>
          {result.risk_score >= 30 && <p className="text-xs text-gray-600 mt-1">Donors will see these AI findings next to the expense:</p>}
          <RiskSignals signals={result.risk_flags} />
        </div>
      )}

      <form onSubmit={submit} className="p-6 space-y-5">
        {/* Invoice upload */}
        <label className={`block border-2 border-dashed rounded-2xl p-5 cursor-pointer transition ${file ? "border-[#00b964] bg-green-50/40" : "border-gray-200 bg-gray-50 hover:border-[#00b964]"}`}>
          <input type="file" accept="image/*,.pdf" className="hidden" onChange={(e) => onFile(e.target.files?.[0] || null)} />
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-white shadow-sm flex items-center justify-center text-[#00b964]">
              {scanning ? <ScanLine className="animate-pulse" size={22} /> : file ? <FileText size={22} /> : <ScanLine size={22} />}
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-bold text-sm text-gray-800 truncate">{file ? file.name : "Upload invoice or bill"}</p>
              <p className="text-xs text-gray-400">{scanning ? "Reading invoice with OCR…" : "PDF or photo · we extract vendor, GSTIN, invoice no., date and total"}</p>
            </div>
          </div>
        </label>

        {scan && (
          <div className="rounded-2xl bg-indigo-50/60 border border-indigo-100 p-4 text-xs space-y-2">
            <div className="flex items-center gap-2 font-bold text-indigo-700">
              <Sparkles size={14} /> AI extracted · {scan.confidence}% confidence
              <span className="font-normal text-indigo-400">({scan.engine})</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-gray-600">
              <span>Total: <b>{scan.total_amount ? fmtINR(scan.total_amount) : "—"}</b></span>
              <span>Invoice: <b>{scan.invoice_number || "—"}</b></span>
              <span>Date: <b>{scan.invoice_date || "—"}</b></span>
              {Object.entries(scan.taxes || {}).map(([k, v]) => <span key={k}>{k}: <b>{fmtINR(v)}</b></span>)}
            </div>
            {scan.already_claimed && (
              <p className="flex items-center gap-1.5 text-red-700 font-semibold"><AlertTriangle size={13} /> This exact file was already claimed for expense #{scan.already_claimed.utilization_id}{scan.already_claimed.campaign_id !== campaignId && ` in campaign #${scan.already_claimed.campaign_id}`}.</p>
            )}
            {scan.gstin_valid === false && (
              <p className="flex items-center gap-1.5 text-red-700 font-semibold"><AlertTriangle size={13} /> GSTIN {scan.vendor_gstin} fails its checksum — check for a typo.</p>
            )}
            {scan.arithmetic_ok === false && (
              <p className="flex items-center gap-1.5 text-amber-700 font-semibold"><AlertTriangle size={13} /> Subtotal + taxes don&apos;t add up to the total.</p>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-bold text-gray-600 mb-1.5">Amount spent (₹) *</label>
            <input type="number" min="1" step="0.01" value={form.amount} onChange={(e) => set("amount", e.target.value)} className={field} />
            {mismatch && <p className="text-[11px] text-amber-600 mt-1">Differs from the invoice total of {fmtINR(scan!.total_amount!)} — this will be flagged.</p>}
          </div>
          <div>
            <label className="block text-xs font-bold text-gray-600 mb-1.5">Category</label>
            <select value={form.category} onChange={(e) => set("category", e.target.value)} className={`${field} capitalize`}>
              {EXPENSE_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="block text-xs font-bold text-gray-600 mb-1.5">What was purchased? *</label>
            <input value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="e.g. 2 wheelchairs and 10 first-aid kits for the PHC" className={field} />
          </div>
          {milestones.length > 0 && (
            <div className="sm:col-span-2">
              <label className="block text-xs font-bold text-gray-600 mb-1.5">Milestone</label>
              <select value={form.milestone_id} onChange={(e) => set("milestone_id", e.target.value)} className={field}>
                <option value="">Not linked to a milestone</option>
                {released.map((m) => <option key={m.id} value={m.id}>{m.sequence}. {m.title} ({fmtINR(m.amount)})</option>)}
              </select>
              {released.length === 0 && <p className="text-[11px] text-gray-400 mt-1">No milestone has been released yet — expenses unlock once donors approve the first one.</p>}
            </div>
          )}
          <div><label className="block text-xs font-bold text-gray-600 mb-1.5">Vendor</label><input value={form.vendor_name} onChange={(e) => set("vendor_name", e.target.value)} className={field} /></div>
          <div><label className="block text-xs font-bold text-gray-600 mb-1.5">Vendor GSTIN</label><input value={form.vendor_gstin} onChange={(e) => set("vendor_gstin", e.target.value.toUpperCase())} maxLength={15} className={`${field} font-mono`} /></div>
          <div><label className="block text-xs font-bold text-gray-600 mb-1.5">Invoice number</label><input value={form.invoice_number} onChange={(e) => set("invoice_number", e.target.value)} className={field} /></div>
          <div><label className="block text-xs font-bold text-gray-600 mb-1.5">Invoice date</label><input type="date" value={form.invoice_date} onChange={(e) => set("invoice_date", e.target.value)} className={field} /></div>
        </div>

        {error && <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-xl px-3 py-2.5 text-xs text-red-700"><AlertTriangle size={14} className="shrink-0 mt-0.5" />{error}</div>}

        <div className="flex justify-end">
          <button type="submit" disabled={submitting || scanning}
            className="px-6 py-3 rounded-2xl font-bold text-white text-sm disabled:opacity-50"
            style={{ background: "linear-gradient(135deg,#00b964,#00d4aa)", boxShadow: "0 8px 20px rgba(0,185,100,0.3)" }}>
            {submitting ? "Recording…" : "Record expense on ledger"}
          </button>
        </div>
      </form>
    </div>
  );
}
