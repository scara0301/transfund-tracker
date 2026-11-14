const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── Auth helpers ────────────────────────────────────────────────────
export function getStoredUser() {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("transfund_user");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setStoredUser(user: { email: string; name: string; role: string }) {
  localStorage.setItem("transfund_user", JSON.stringify(user));
}

export function clearStoredUser() {
  localStorage.removeItem("transfund_user");
}

// ─── Auth API ─────────────────────────────────────────────────────────
type AuthUser = { id: number; name: string; email: string; role: "donor" | "organizer" };

async function _postAuth(path: string, body: unknown) {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Could not reach server. Is the backend running?");
  }
  if (!res.ok) {
    let detail = "Request failed";
    try {
      const j = await res.json();
      if (j?.detail) detail = j.detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<{ message: string; user: AuthUser }>;
}

export function upsertUser(data: {
  role: "donor" | "organizer";
  name: string;
  email: string;
  password?: string;
}) {
  return _postAuth("/auth/upsert", data);
}

export function registerUser(data: {
  role: "donor" | "organizer";
  name: string;
  email: string;
  password: string;
}) {
  return _postAuth("/auth/register", data);
}

export function loginUser(data: {
  role: "donor" | "organizer";
  name: string;
  email: string;
  password: string;
}) {
  return _postAuth("/auth/login", data);
}

// ─── Campaign API ─────────────────────────────────────────────────────
export async function getCampaigns(params?: { category?: string; organizer_email?: string }) {
  const qs = new URLSearchParams();
  if (params?.category && params.category !== "All") qs.set("category", params.category);
  if (params?.organizer_email) qs.set("organizer_email", params.organizer_email);
  const res = await fetch(`${API}/campaigns/?${qs.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch campaigns");
  return res.json();
}

export async function getCampaign(id: number) {
  const res = await fetch(`${API}/campaigns/${id}`);
  if (!res.ok) throw new Error("Campaign not found");
  return res.json();
}

export async function createCampaign(formData: FormData) {
  return req("/campaigns/", { method: "POST", body: formData });
}

export async function deleteCampaign(id: number) {
  return req(`/campaigns/${id}`, { method: "DELETE" });
}

export async function updateCampaign(id: number, formData: FormData) {
  const res = await fetch(`${API}/campaigns/${id}`, { method: "PATCH", body: formData });
  if (!res.ok) {
    let detail = "Failed to update campaign";
    try { const j = await res.json(); if (j?.detail) detail = j.detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export async function closeCampaign(id: number, reason: string) {
  const res = await fetch(`${API}/campaigns/${id}/close`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) throw new Error("Failed to close campaign");
  return res.json();
}

// ─── Donation API ─────────────────────────────────────────────────────
export async function makeDonation(data: {
  campaign_id: number;
  donor_name: string;
  donor_email: string;
  amount: number;
}) {
  const res = await fetch(`${API}/donations/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    let detail = "Failed to record donation";
    try { const j = await res.json(); if (j?.detail) detail = j.detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export async function getDonorDonations(donor_email: string) {
  const res = await fetch(`${API}/donations/?donor_email=${encodeURIComponent(donor_email)}`);
  if (!res.ok) throw new Error("Failed to fetch donor donations");
  return res.json();
}

export async function getOrganizerDonations(organizer_email: string) {
  const res = await fetch(`${API}/donations/?organizer_email=${encodeURIComponent(organizer_email)}`);
  if (!res.ok) throw new Error("Failed to fetch organizer donations");
  return res.json();
}

export async function getCampaignDonations(campaign_id: number) {
  const res = await fetch(`${API}/donations/?campaign_id=${campaign_id}`);
  if (!res.ok) throw new Error("Failed to fetch campaign donations");
  return res.json();
}

// ─── Utilization API ──────────────────────────────────────────────
export async function getUtilizations(campaign_id: number) {
  const res = await fetch(`${API}/utilizations/?campaign_id=${campaign_id}`);
  if (!res.ok) throw new Error("Failed to fetch utilizations");
  return res.json();
}

export async function getUtilizationSummary(campaign_id: number) {
  const res = await fetch(`${API}/utilizations/summary/${campaign_id}`);
  if (!res.ok) throw new Error("Failed to fetch utilization summary");
  return res.json();
}

// ─── Campaign Updates API ─────────────────────────────────────────
export async function getCampaignUpdates(campaign_id: number) {
  const res = await fetch(`${API}/campaign-updates/?campaign_id=${campaign_id}`);
  if (!res.ok) throw new Error("Failed to fetch updates");
  return res.json();
}

export async function createCampaignUpdate(formData: FormData) {
  const res = await fetch(`${API}/campaign-updates/`, { method: "POST", body: formData });
  if (!res.ok) {
    let detail = "Failed to post update";
    try { const j = await res.json(); if (j?.detail) detail = j.detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export async function deleteCampaignUpdate(updateId: number) {
  const res = await fetch(`${API}/campaign-updates/${updateId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete update");
  return res.json();
}

// ─── Donor Impact API ─────────────────────────────────────────────
export async function getDonorImpact(donor_email: string) {
  const res = await fetch(`${API}/donations/impact?donor_email=${encodeURIComponent(donor_email)}`);
  if (!res.ok) throw new Error("Failed to fetch donor impact");
  return res.json();
}

// ─── Shared helpers ───────────────────────────────────────────────
async function req<T = any>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, init);
  } catch {
    throw new Error("Could not reach server. Is the backend running?");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try { const j = await res.json(); if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new Error(detail);
  }
  return res.json();
}
const jsonBody = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// ─── AI types ─────────────────────────────────────────────────────
export type RiskSignal = { code: string; label: string; weight: number; detail: string };
export type RiskResult = { score: number; level: "low" | "medium" | "high"; signals: RiskSignal[] };
export type InvoiceScan = {
  vendor_name: string | null;
  vendor_gstin: string | null;
  gstin_valid: boolean | null;
  invoice_number: string | null;
  invoice_date: string | null;
  subtotal: number | null;
  taxes: Record<string, number>;
  total_amount: number | null;
  arithmetic_ok: boolean | null;
  engine: string;
  confidence: number;
  ocr_confidence: number | null;
  file_hash: string;
  already_claimed: { utilization_id: number; campaign_id: number } | null;
};

// ─── Payments API (Razorpay / demo) ───────────────────────────────
export type PaymentConfig = { provider: "razorpay" | "demo"; key_id: string | null; methods: string[] };
export type PaymentOrder = {
  order_id: string; provider: "razorpay" | "demo"; key_id: string | null;
  amount: number; amount_paise: number; currency: string; campaign_title: string;
};
export type DonationResult = {
  id: number; amount: number; receipt_number: string | null; payment_method: string | null;
  transaction_id: string | null; donated_at: string;
  ledger: { block_index?: number; block_hash: string | null; data_hash?: string };
  risk: { score: number | null; level?: string };
};

export const getPaymentConfig = () => req<PaymentConfig>("/payments/config");
export const createPaymentOrder = (data: {
  campaign_id: number; donor_name: string; donor_email: string; amount: number; donor_id?: number;
}) => req<PaymentOrder>("/payments/order", jsonBody(data));
export const verifyPayment = (data: {
  order_id: string; payment_id?: string; signature?: string; payment_method?: string;
}) => req<DonationResult>("/payments/verify", jsonBody(data));

// ─── Milestones / escrow API ──────────────────────────────────────
export type Tally = {
  round: number; approve_weight: number; reject_weight: number; voter_count: number;
  approve_count: number; reject_count: number; turnout_percent: number; quorum_percent: number;
  quorum_met: boolean; window_over: boolean; can_finalize: boolean; passing: boolean;
};
export type Milestone = {
  id: number; campaign_id: number; sequence: number; title: string; description: string | null;
  amount: number; status: "pending" | "voting" | "released" | "rejected";
  proof_url: string | null; proof_note: string | null; proof_hash: string | null;
  submitted_at: string | null; voting_deadline: string | null; released_at: string | null;
  ledger_hash: string | null; tally: Tally; my_vote: "approve" | "reject" | null;
};
export type Funds = {
  escrow: boolean; raised: number; released: number; locked_in_escrow: number; utilized: number; spendable: number;
};
export type MilestoneState = {
  campaign_id: number; funds: Funds; next_milestone_id: number | null; voting_hours: number;
  quorum_percent: number; my_weight: number; milestones: Milestone[];
};

export const getMilestones = (campaign_id: number, donor_email?: string) =>
  req<MilestoneState>(`/milestones/?campaign_id=${campaign_id}${donor_email ? `&donor_email=${encodeURIComponent(donor_email)}` : ""}`);
export const setMilestonePlan = (campaign_id: number, organizer_email: string, milestones: { title: string; amount: number; description?: string }[]) =>
  req<MilestoneState>("/milestones/plan", jsonBody({ campaign_id, organizer_email, milestones }));
export const submitMilestoneProof = (id: number, form: FormData) =>
  req<Milestone>(`/milestones/${id}/proof`, { method: "POST", body: form });
export const voteMilestone = (id: number, donor_email: string, approve: boolean, comment?: string) =>
  req<Milestone>(`/milestones/${id}/vote`, jsonBody({ donor_email, approve, comment }));
export const finalizeMilestone = (id: number, organizer_email: string) =>
  req<Milestone>(`/milestones/${id}/finalize`, jsonBody({ organizer_email }));

// ─── Ledger (blockchain) API ──────────────────────────────────────
export type LedgerBlock = {
  index: number; timestamp: string; event_type: string; campaign_id: number | null;
  entity_type: string | null; entity_id: number | null; payload: Record<string, unknown>;
  data_hash: string; prev_hash: string; nonce: number; block_hash: string; anchor_id: number | null;
};
export type LedgerVerification = {
  valid: boolean; chain_valid: boolean; chain_length: number; tip_hash: string | null; difficulty: number;
  broken_at: number | null; drift_count: number; issue_count: number; campaign_blocks: number;
  issues: { type: string; block_index: number | null; campaign_id: number | null; problems: string[] }[];
  last_anchor: { to_block: number; merkle_root: string; network: string; tx_hash: string | null; created_at: string } | null;
  verified_at: string;
};
export type LedgerStatus = {
  chain_length: number; tip_hash: string | null; difficulty: number; unanchored_blocks: number;
  anchoring: { enabled: boolean; configured: boolean; network: string | null; contract_address: string | null; explorer_tx_url: string | null };
  anchors: { id: number; from_block: number; to_block: number; merkle_root: string; network: string; tx_hash: string | null; created_at: string }[];
};

export const getLedger = (params: { campaign_id?: number; limit?: number; before?: number; event_type?: string } = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
  return req<{ chain_length: number; blocks: LedgerBlock[] }>(`/ledger/?${qs}`);
};
export const verifyLedger = (campaign_id?: number) =>
  req<LedgerVerification>(`/ledger/verify${campaign_id ? `?campaign_id=${campaign_id}` : ""}`);
export const getLedgerStatus = () => req<LedgerStatus>("/ledger/status");
export const anchorLedger = () => req<any>("/ledger/anchor", { method: "POST" });

// ─── AI API ───────────────────────────────────────────────────────
export function scanInvoice(file: File) {
  const fd = new FormData();
  fd.append("file", file);
  return req<InvoiceScan>("/ai/ocr", { method: "POST", body: fd });
}
export const campaignPrecheck = (data: {
  title: string; description: string; category: string; goal_amount: number; organizer_email: string; milestone_count: number;
}) => req<RiskResult>("/ai/campaign-precheck", jsonBody(data));
export const getCampaignAnalysis = (campaign_id: number) => req<any>(`/ai/campaign/${campaign_id}/analysis`);
export const getFraudAlerts = (organizer_email?: string) =>
  req<any>(`/ai/alerts${organizer_email ? `?organizer_email=${encodeURIComponent(organizer_email)}` : ""}`);

export async function createUtilization(form: FormData) {
  return req<any>("/utilizations/", { method: "POST", body: form });
}

export const errMsg = (e: unknown, fallback = "Something went wrong") => (e instanceof Error ? e.message : fallback);

export const shortHash = (h?: string | null, n = 10) => (h ? `${h.slice(0, n)}…${h.slice(-4)}` : "—");

// File URL helper (uploads served by backend)
export const fileUrl = (path: string) => `${API}${path}`;

// ─── Formatters ───────────────────────────────────────────────────────
export function fmtINR(amount: number) {
  return `₹${amount.toLocaleString("en-IN")}`;
}

export function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
