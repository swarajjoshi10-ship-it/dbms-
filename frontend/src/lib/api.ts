export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public body: Record<string, unknown> = {}) {
    super(message);
  }
}

const TOKEN_KEY = "finledger.token";

// The JWT lives in sessionStorage: it is gone when the tab closes, and expires after 60 minutes anyway.
export const tokenStore = {
  get: (): string | null => {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (token: string | null) => {
    try {
      if (token) sessionStorage.setItem(TOKEN_KEY, token);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      // Storage unavailable: the session simply does not survive a reload.
    }
  },
};

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

export async function api<T>(path: string, options: { method?: string; body?: unknown; headers?: Record<string, string> } = {}): Promise<T> {
  const headers: Record<string, string> = { ...options.headers };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: options.method ?? (options.body !== undefined ? "POST" : "GET"),
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the FinLedger API. Is the backend running?");
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && token) onUnauthorized();
    const fields = Array.isArray(data.fields)
      ? data.fields.map((f: { field: string; message: string }) => `${f.field}: ${f.message}`).join("; ")
      : "";
    throw new ApiError(response.status, data.error ?? "ERROR", fields ? `${data.detail} (${fields})` : (data.detail ?? "Request failed"), data);
  }
  return data as T;
}

// ---------- shared types ----------
export type Role = "CUSTOMER" | "STAFF" | "ADMIN";
export interface User { id: string; username: string; email: string; role: Role; is_active: boolean; created_at: string }
export interface CustomerProfile { id: string; full_name: string; phone: string | null; pan_number: string | null; kyc_status: string }
export interface Account {
  id: string; account_number: string; account_type: string; currency: string; cached_balance: string; status: string; created_at: string;
  owner_name?: string | null; owner_username?: string | null; kyc_status?: string | null;
}
export interface Prediction { id: string; model_version: string; risk_score: string; decision: string; rule_flags: string[]; explanation: string; review_status: string }
export interface Transfer {
  id: string; idempotency_key: string; status: string; amount: string; currency: string;
  source_account_id: string; source_account_number: string; destination_account_id: string; destination_account_number: string;
  failure_reason: string | null; created_at: string; posted_at: string | null; replayed: boolean; prediction: Prediction | null;
}
export interface StatementLine {
  entry_id: string; transaction_id: string; transaction_type: string; description: string; transfer_request_id: string | null;
  entry_type: "DEBIT" | "CREDIT"; amount: string; running_balance: string; counterparty: string | null; created_at: string;
}
export interface PayeePreview { account_id: string; account_number_masked: string; holder_display_name: string; account_type: string; status: string }
export interface SavedPayee { id: string; nickname: string; account_id: string; account_number_masked: string; holder_display_name: string; created_at: string }
export interface Product { id: string; name: string; code: string; product_type: string; annual_yield_rate: string; min_amount: string; term_months: number; is_active: boolean }
export interface Investment {
  id: string; product_code: string; product_name: string; product_type: string; principal: string; annual_yield_rate: string;
  start_date: string; maturity_date: string; expected_maturity_value: string; status: string;
}
export interface Alert {
  id: string; transfer_request_id: string; model_version: string; risk_score: string; decision: string; rule_flags: string[];
  feature_snapshot: Record<string, number | null>; explanation: string; review_status: string; reviewed_by: string | null;
  review_notes: string | null; reviewed_at: string | null; created_at: string; amount: string; transfer_status: string;
  source_account_number: string; destination_account_number: string; sender_username: string;
  notes?: { id: string; author: string; note: string; created_at: string }[];
}
export interface CaseEvent { id: string; event_type: string; message: string; actor: string | null; created_at: string }
export interface Dispute {
  id: string; transfer_request_id: string; customer_name: string; reason: string; description: string; status: string;
  assigned_staff: string | null; resolution_notes: string | null; amount: string; transfer_status: string;
  destination_account_number: string; created_at: string; updated_at: string; resolved_at: string | null; events: CaseEvent[];
}
export interface GraphFinding {
  id: string; finding_type: string; primary_account_number: string; involved_account_numbers: string[]; total_amount: string;
  severity: string; details: Record<string, unknown>; status: string; created_at: string;
}
export interface LabRun {
  id: string; model_version: string; scenario: Record<string, number>; n_samples: number; accuracy: string; precision_score: string;
  recall_score: string; f1_score: string; confusion: { tn: number; fp: number; fn: number; tp: number }; created_at: string;
}
export interface AuditRow {
  id: number; actor: string | null; action: string; entity_type: string; entity_id: string; ip_address: string | null;
  metadata_json: Record<string, unknown>; created_at: string;
}
export interface Reconciliation {
  checked_at: string; accounts_checked: number; discrepancies: number; unbalanced_transactions: number; system_total: string; ok: boolean;
  rows: { account_number: string; account_type: string; status: string; cached_balance: string; ledger_balance: string; discrepancy: string; leg_count: number }[];
}
