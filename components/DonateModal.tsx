"use client";

import { useEffect, useState } from "react";
import {
  getPaymentConfig, createPaymentOrder, verifyPayment, fmtINR, shortHash,
  type PaymentConfig, type DonationResult, type PaymentOrder,
} from "@/lib/api";
import { errMsg } from "@/lib/api";
import { CheckCircle, Heart, Smartphone, CreditCard, Landmark, Wallet, ShieldCheck, Link2, X } from "lucide-react";

const QUICK_AMOUNTS = [500, 1000, 2000, 5000];
const METHODS = [
  { id: "UPI", label: "UPI", Icon: Smartphone },
  { id: "Card", label: "Card", Icon: CreditCard },
  { id: "NetBanking", label: "NetBanking", Icon: Landmark },
  { id: "Wallet", label: "Wallet", Icon: Wallet },
] as const;
const BANKS = ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank", "Punjab National Bank"];

declare global {
  interface Window { Razorpay?: any }
}

function loadRazorpay(): Promise<boolean> {
  return new Promise((resolve) => {
    if (window.Razorpay) return resolve(true);
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve(true);
    s.onerror = () => resolve(false);
    document.body.appendChild(s);
  });
}

export default function DonateModal({ campaign, user, initialAmount = "", onClose, onDonated, onLimit }: {
  campaign: { id: number; title: string };
  user: { name: string; email: string; id?: number } | null;
  initialAmount?: string;
  onClose: () => void;
  onDonated: (r: DonationResult) => void;
  onLimit: (limit: string, remaining: string) => void;
}) {
  const [config, setConfig] = useState<PaymentConfig | null>(null);
  const [amount, setAmount] = useState(initialAmount);
  const [step, setStep] = useState<"amount" | "demo-checkout" | "done">("amount");
  const [order, setOrder] = useState<PaymentOrder | null>(null);
  const [method, setMethod] = useState<(typeof METHODS)[number]["id"]>("UPI");
  const [upiId, setUpiId] = useState("");
  const [bank, setBank] = useState(BANKS[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<DonationResult | null>(null);

  useEffect(() => { getPaymentConfig().then(setConfig).catch(() => setConfig({ provider: "demo", key_id: null, methods: [] })); }, []);

  const finish = (r: DonationResult) => { setResult(r); setStep("done"); onDonated(r); };

  const start = async () => {
    const amt = parseFloat(amount);
    if (!amt || amt < 1) return setError("Enter a valid amount");
    if (!user) return setError("Please log in to donate");
    setBusy(true); setError("");
    try {
      const o = await createPaymentOrder({ campaign_id: campaign.id, donor_name: user.name, donor_email: user.email, amount: amt, donor_id: user.id });
      setOrder(o);
      if (o.provider === "demo") { setStep("demo-checkout"); return; }

      if (!(await loadRazorpay())) throw new Error("Couldn't load Razorpay checkout. Check your connection.");
      await new Promise<void>((resolve, reject) => {
        const rzp = new window.Razorpay({
          key: o.key_id,
          amount: o.amount_paise,
          currency: "INR",
          name: "TransFund",
          description: o.campaign_title,
          order_id: o.order_id,
          prefill: { name: user.name, email: user.email },
          notes: { campaign_id: String(campaign.id) },
          theme: { color: "#00b964" },
          handler: async (resp: any) => {
            try {
              finish(await verifyPayment({ order_id: resp.razorpay_order_id, payment_id: resp.razorpay_payment_id, signature: resp.razorpay_signature }));
              resolve();
            } catch (e) { reject(e); }
          },
          modal: { ondismiss: () => reject(new Error("Payment cancelled")) },
        });
        rzp.on("payment.failed", (r: any) => reject(new Error(r?.error?.description || "Payment failed")));
        rzp.open();
      });
    } catch (err: unknown) {
      const msg = errMsg(err, "");
      if (msg.startsWith("DAILY_LIMIT_REACHED|")) {
        const [, limit, remaining] = msg.split("|");
        onLimit(limit, remaining);
      } else setError(msg || "Payment failed. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const payDemo = async () => {
    if (!order) return;
    if (method === "UPI" && !/^[\w.\-]{2,}@[a-zA-Z]{2,}$/.test(upiId)) return setError("Enter a valid UPI ID, e.g. name@okaxis");
    setBusy(true); setError("");
    try { finish(await verifyPayment({ order_id: order.order_id, payment_method: method })); }
    catch (e: unknown) { setError(errMsg(e)); }
    finally { setBusy(false); }
  };

  const amt = parseFloat(amount) || 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-3xl w-full max-w-md shadow-2xl overflow-hidden max-h-[92vh] overflow-y-auto"
        style={{ boxShadow: "0 32px 80px rgba(0,0,0,0.15), 0 8px 24px rgba(0,185,100,0.1)" }}>
        <div className="h-1.5 w-full" style={{ background: "linear-gradient(90deg,#00b964,#00d4aa,#0069ff)" }} />
        <div className="p-8">
          {step === "done" && result ? (
            <div className="text-center">
              <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-4"><CheckCircle size={36} className="text-[#00b964]" /></div>
              <h3 className="text-xl font-extrabold text-gray-900 mb-1">Thank you! 🎉</h3>
              <p className="text-gray-500 text-sm mb-5">{fmtINR(result.amount)} donated via {result.payment_method || "online payment"}.</p>
              <div className="text-left rounded-2xl bg-gray-50 border border-gray-100 p-4 space-y-2 text-xs">
                <div className="flex justify-between"><span className="text-gray-400">Receipt</span><b className="text-gray-800">{result.receipt_number}</b></div>
                <div className="flex justify-between gap-3"><span className="text-gray-400">Transaction</span><code className="font-mono text-gray-700 truncate">{result.transaction_id}</code></div>
                <div className="flex justify-between gap-3"><span className="text-gray-400 inline-flex items-center gap-1"><Link2 size={11} />Ledger block</span>
                  <code className="font-mono text-gray-700 truncate">{result.ledger.block_index !== undefined && `#${result.ledger.block_index} · `}{shortHash(result.ledger.block_hash, 12)}</code></div>
                <p className="text-[11px] text-gray-400 pt-1 inline-flex items-center gap-1"><ShieldCheck size={12} className="text-[#00b964]" />Your donation is now a tamper-evident block on the TransFund ledger.</p>
              </div>
              <button onClick={onClose} className="mt-6 w-full py-3 rounded-2xl text-sm font-bold text-white" style={{ background: "linear-gradient(135deg,#00b964,#00d4aa)" }}>Done</button>
            </div>
          ) : step === "demo-checkout" && order ? (
            <>
              <div className="flex justify-between items-start mb-5">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-wide text-amber-600 bg-amber-50 inline-block px-2 py-0.5 rounded-md mb-1">Demo checkout · no real money</p>
                  <h3 className="text-xl font-extrabold text-gray-900">Pay {fmtINR(order.amount)}</h3>
                  <p className="text-xs text-gray-400 mt-0.5 font-mono">{order.order_id}</p>
                </div>
                <button onClick={onClose} className="text-gray-300 hover:text-gray-600"><X size={20} /></button>
              </div>
              <div className="grid grid-cols-4 gap-2 mb-5">
                {METHODS.map(({ id, label, Icon }) => (
                  <button key={id} onClick={() => setMethod(id)}
                    className={`flex flex-col items-center gap-1 py-3 rounded-xl border-2 text-[11px] font-bold transition ${method === id ? "border-[#00b964] bg-green-50 text-[#00b964]" : "border-gray-100 text-gray-500 hover:border-gray-200"}`}>
                    <Icon size={18} />{label}
                  </button>
                ))}
              </div>
              {method === "UPI" && (
                <input value={upiId} onChange={(e) => setUpiId(e.target.value)} placeholder="yourname@okaxis"
                  className="w-full px-4 py-3 border-2 border-gray-100 bg-gray-50 rounded-2xl text-sm focus:outline-none focus:border-[#00b964] focus:bg-white" />
              )}
              {method === "Card" && (
                <div className="space-y-2">
                  <input placeholder="4111 1111 1111 1111" className="w-full px-4 py-3 border-2 border-gray-100 bg-gray-50 rounded-2xl text-sm font-mono focus:outline-none focus:border-[#00b964]" />
                  <div className="grid grid-cols-2 gap-2">
                    <input placeholder="MM / YY" className="px-4 py-3 border-2 border-gray-100 bg-gray-50 rounded-2xl text-sm focus:outline-none focus:border-[#00b964]" />
                    <input placeholder="CVV" className="px-4 py-3 border-2 border-gray-100 bg-gray-50 rounded-2xl text-sm focus:outline-none focus:border-[#00b964]" />
                  </div>
                  <p className="text-[11px] text-gray-400">Demo mode: card details are not sent anywhere.</p>
                </div>
              )}
              {method === "NetBanking" && (
                <select value={bank} onChange={(e) => setBank(e.target.value)} className="w-full px-4 py-3 border-2 border-gray-100 bg-gray-50 rounded-2xl text-sm focus:outline-none focus:border-[#00b964]">
                  {BANKS.map((b) => <option key={b}>{b}</option>)}
                </select>
              )}
              {method === "Wallet" && <p className="text-sm text-gray-500">Paytm · PhonePe · Amazon Pay</p>}
              {error && <p className="mt-3 text-xs text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">{error}</p>}
              <button onClick={payDemo} disabled={busy}
                className="mt-5 w-full flex items-center justify-center gap-2 text-white py-3.5 rounded-2xl font-bold text-sm disabled:opacity-60"
                style={{ background: "linear-gradient(135deg,#00b964,#00d4aa)", boxShadow: "0 8px 20px rgba(0,185,100,0.35)" }}>
                {busy ? <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" /> Verifying payment…</> : <>Pay {fmtINR(order.amount)}</>}
              </button>
            </>
          ) : (
            <>
              <div className="flex justify-between items-start mb-6">
                <div>
                  <h3 className="text-xl font-extrabold text-gray-900">Make a Donation</h3>
                  <p className="text-sm text-gray-400 mt-1 line-clamp-1">{campaign.title}</p>
                </div>
                <button onClick={onClose} className="text-gray-300 hover:text-gray-600"><X size={20} /></button>
              </div>
              <p className="text-xs font-semibold text-gray-400 uppercase mb-2 tracking-wider">Quick Select</p>
              <div className="grid grid-cols-4 gap-2 mb-4">
                {QUICK_AMOUNTS.map((q) => (
                  <button key={q} onClick={() => setAmount(String(q))}
                    className={`py-2.5 rounded-xl text-sm font-bold border-2 transition-all ${amount === String(q) ? "border-[#00b964] bg-green-50 text-[#00b964]" : "border-gray-100 bg-gray-50 text-gray-600 hover:border-[#00b964] hover:text-[#00b964]"}`}>
                    {fmtINR(q)}
                  </button>
                ))}
              </div>
              <div className="relative mb-4">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 font-semibold text-sm">₹</span>
                <input id="donate-amount" type="number" min="1" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Enter custom amount"
                  className="w-full pl-8 pr-4 py-3 border-2 border-gray-100 bg-gray-50 rounded-2xl text-sm focus:outline-none focus:border-[#00b964] focus:bg-white transition-all" />
              </div>
              {error && <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-3 py-2.5 mb-4"><span className="text-xs">⚠️</span><p className="text-red-600 text-xs">{error}</p></div>}
              <button id="btn-confirm-donate" onClick={start} disabled={busy || !config}
                className="w-full flex items-center justify-center gap-2 text-white py-3.5 rounded-2xl font-bold text-sm disabled:opacity-60 disabled:cursor-not-allowed transition-all"
                style={{ background: busy ? "#9ca3af" : "linear-gradient(135deg,#00b964,#00d4aa)", boxShadow: busy ? "none" : "0 8px 20px rgba(0,185,100,0.35)" }}>
                {busy ? <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" /> Processing…</>
                  : <><Heart size={15} /> {amt ? `Continue to pay ${fmtINR(amt)}` : "Continue to payment"}</>}
              </button>
              <div className="flex items-center justify-center gap-3 mt-4 text-[11px] text-gray-400">
                <span>UPI</span>·<span>Cards</span>·<span>NetBanking</span>·<span>Wallets</span>
                <span className="ml-1 font-semibold text-gray-500">{config?.provider === "razorpay" ? "Secured by Razorpay" : "Demo mode"}</span>
              </div>
              <p className="text-xs text-gray-400 text-center mt-2">Donating as <span className="font-semibold text-gray-600">{user?.name || "Guest"}</span> · {user?.email}</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
