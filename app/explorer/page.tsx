"use client";

import Link from "next/link";
import Logo from "@/components/Logo";
import LedgerPanel from "@/components/LedgerPanel";
import { ShieldCheck, Hash, Globe } from "lucide-react";

export default function ExplorerPage() {
  return (
    <div className="min-h-screen bg-[#fdf6f0]">
      <nav className="flex justify-between items-center px-6 md:px-8 py-4 bg-white/80 backdrop-blur-xl border-b border-gray-100 sticky top-0 z-40">
        <Logo size={34} href="/" />
        <Link href="/login" className="text-sm font-bold px-4 py-2 rounded-full text-white" style={{ background: "linear-gradient(135deg,#00b964,#00d4aa)" }}>Sign in</Link>
      </nav>
      <main className="max-w-5xl mx-auto p-4 md:p-6 space-y-6 pb-16">
        <div className="pt-4">
          <p className="text-sm text-indigo-600 font-semibold mb-1">Public ledger explorer</p>
          <h1 className="text-3xl font-extrabold text-gray-900">Don&apos;t trust us — verify.</h1>
          <p className="text-gray-500 mt-2 max-w-2xl">
            Every donation, milestone vote, fund release and expense on TransFund is recorded as a block that commits to the one before it.
            Anyone can re-run the verification below; altering a single record anywhere breaks the chain.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            { Icon: Hash, title: "SHA-256 hash chain", text: "Each block stores the previous block's hash, plus a small proof-of-work." },
            { Icon: ShieldCheck, title: "Database cross-check", text: "Verification re-derives each donation and expense from the live database to catch silent edits." },
            { Icon: Globe, title: "Public-chain anchoring", text: "Merkle roots of the ledger can be committed to an EVM smart contract for external proof." },
          ].map(({ Icon, title, text }) => (
            <div key={title} className="bg-white rounded-2xl border border-gray-100 p-5">
              <Icon size={18} className="text-indigo-600 mb-2" />
              <p className="font-bold text-gray-900 text-sm">{title}</p>
              <p className="text-xs text-gray-500 mt-1">{text}</p>
            </div>
          ))}
        </div>
        <LedgerPanel title="TransFund chain" pageSize={25} />
      </main>
    </div>
  );
}
