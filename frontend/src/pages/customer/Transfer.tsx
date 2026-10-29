import { useEffect, useState, type FormEvent } from "react";
import { Badge, Button, Card, Empty, Field, Input, Notice, PageHeader, Select } from "../../components/ui";
import { api, ApiError, type Account, type PayeePreview, type SavedPayee, type Transfer as TransferT } from "../../lib/api";
import { isValidAmount, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const newKey = () => crypto.randomUUID();

export default function Transfer() {
  const accounts = useApi<Account[]>("/accounts");
  const payees = useApi<SavedPayee[]>("/payees");
  const [source, setSource] = useState("");
  const [destination, setDestination] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [preview, setPreview] = useState<PayeePreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  // One key per intended transfer: a retry after a network error re-sends the same key.
  const [idempotencyKey, setIdempotencyKey] = useState(newKey);
  const [result, setResult] = useState<TransferT | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [nickname, setNickname] = useState("");

  const spendable = (accounts.data ?? []).filter((a) => (a.account_type === "SAVINGS" || a.account_type === "CURRENT") && a.status === "ACTIVE");
  const from = spendable.find((a) => a.id === source) ?? spendable[0];

  useEffect(() => {
    setPreview(null);
    setPreviewError(null);
    const number = destination.trim().toUpperCase();
    if (number.length < 12) return;
    const timer = setTimeout(() => {
      api<PayeePreview>(`/accounts/lookup/${encodeURIComponent(number)}`)
        .then(setPreview)
        .catch((e) => setPreviewError((e as Error).message));
    }, 350);
    return () => clearTimeout(timer);
  }, [destination]);

  function startNew() {
    setIdempotencyKey(newKey());
    setResult(null);
    setError(null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!from) return;
    if (!isValidAmount(amount)) return setError("Enter a positive amount with at most two decimals.");
    setBusy(true);
    setError(null);
    try {
      const t = await api<TransferT>("/transfers", {
        body: { source_account_id: from.id, destination_account_number: destination.trim().toUpperCase(), amount, description: description || null },
        headers: { "Idempotency-Key": idempotencyKey },
      });
      setResult(t);
      setAmount("");
      setDescription("");
      setIdempotencyKey(newKey());
      await accounts.reload();
    } catch (err) {
      const apiErr = err as ApiError;
      setError(apiErr.message);
      // A refused transfer is final (it is recorded as FAILED), so the next attempt is a new request.
      // Only a network failure keeps the key, so the retry is recognised as the same request.
      if (apiErr.status !== 0) setIdempotencyKey(newKey());
    } finally {
      setBusy(false);
    }
  }

  async function savePayee() {
    try {
      await api("/payees", { body: { account_number: destination.trim().toUpperCase(), nickname } });
      setNickname("");
      await payees.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function usePayee(p: SavedPayee) {
    const res = await api<{ account_number: string }>(`/payees/${p.id}/account-number`);
    setDestination(res.account_number);
  }

  async function removePayee(p: SavedPayee) {
    await api(`/payees/${p.id}`, { method: "DELETE" });
    await payees.reload();
  }

  return (
    <>
      <PageHeader title="Send money" subtitle="Transfers between FinLedger accounts settle instantly as a balanced debit and credit." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="New transfer" className="lg:col-span-2">
          <form onSubmit={submit} className="space-y-4">
            {result && (
              <Notice kind="success">
                {money(result.amount)} sent to {result.destination_account_number}. Status <strong>{result.status}</strong>
                {result.replayed && " (this was a retry; the original transfer was returned, nothing was sent twice)"}.{" "}
                <button type="button" className="underline" onClick={startNew}>New transfer</button>
              </Notice>
            )}
            {error && <Notice>{error}</Notice>}
            <Field label="From">
              <Select value={from?.id ?? ""} onChange={(e) => setSource(e.target.value)}>
                {spendable.map((a) => <option key={a.id} value={a.id}>{a.account_number} · {money(a.cached_balance)} available</option>)}
              </Select>
            </Field>
            <Field label="To account number" hint="PayeeGuard shows who owns the account before you send.">
              <Input value={destination} onChange={(e) => setDestination(e.target.value)} placeholder="INR-SAV-XXXXXXXX" className="font-mono uppercase" required />
            </Field>
            {preview && (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-sm">
                <div>
                  <span className="font-medium text-emerald-900">{preview.holder_display_name}</span>
                  <span className="ml-2 font-mono text-xs text-emerald-800">{preview.account_number_masked}</span>
                  <span className="ml-2"><Badge value={preview.status} /></span>
                </div>
                <div className="flex gap-2">
                  <Input value={nickname} onChange={(e) => setNickname(e.target.value)} placeholder="Nickname" className="w-32 py-1" />
                  <Button type="button" variant="secondary" className="py-1" onClick={savePayee} disabled={!nickname.trim()}>Save payee</Button>
                </div>
              </div>
            )}
            {previewError && <p className="text-sm text-rose-700">{previewError}</p>}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Amount (₹)"><Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required /></Field>
              <Field label="Note (optional)"><Input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={140} /></Field>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="font-mono text-xs text-slate-400" title="Idempotency key">key {idempotencyKey.slice(0, 8)}…</span>
              <Button type="submit" disabled={busy || !from}>{busy ? "Sending…" : "Send"}</Button>
            </div>
          </form>
        </Card>

        <Card title="Saved payees">
          {payees.data?.length === 0 && <Empty>Look up an account number to save it here.</Empty>}
          <ul className="divide-y divide-slate-100">
            {payees.data?.map((p) => (
              <li key={p.id} className="flex items-center justify-between py-2.5">
                <button type="button" onClick={() => usePayee(p)} className="text-left">
                  <div className="text-sm font-medium text-slate-800">{p.nickname}</div>
                  <div className="text-xs text-slate-500">{p.holder_display_name} · <span className="font-mono">{p.account_number_masked}</span></div>
                </button>
                <button type="button" onClick={() => removePayee(p)} className="text-xs text-slate-400 hover:text-rose-600">Remove</button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
