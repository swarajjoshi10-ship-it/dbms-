import { useState } from "react";
import { Badge, Button, Card, Empty, Input, Notice, PageHeader, RiskMeter, Select, Table, Td } from "../../components/ui";
import { api, type Transfer } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { dateTime, label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

export default function Transfers() {
  const { session } = useAuth();
  const isAdmin = session?.user.role === "ADMIN";
  const [status, setStatus] = useState("");
  const [account, setAccount] = useState("");
  const [query, setQuery] = useState("");
  const transfers = useApi<Transfer[]>(`/transfers?limit=200${status ? `&status=${status}` : ""}${query ? `&account_number=${encodeURIComponent(query)}` : ""}`);
  const [reversing, setReversing] = useState<Transfer | null>(null);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  async function reverse() {
    if (!reversing) return;
    try {
      await api(`/admin/transfers/${reversing.id}/reverse`, { body: { reason } });
      setMessage({ kind: "success", text: `Reversed ${money(reversing.amount)}. A CORRECTION_REVERSAL posting was added; the original stays on record.` });
      setReversing(null);
      setReason("");
      await transfers.reload();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    }
  }

  return (
    <>
      <PageHeader title="Transfers" subtitle={isAdmin ? "Search transfers. Admins can post a correction reversal." : "Search all customer transfers."} />
      <div className="mb-4 flex flex-wrap gap-3">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-auto">
          <option value="">All statuses</option>
          {["POSTED", "FAILED", "REVERSED"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </Select>
        <form onSubmit={(e) => { e.preventDefault(); setQuery(account.trim()); }} className="flex gap-2">
          <Input value={account} onChange={(e) => setAccount(e.target.value)} placeholder="Account number" className="w-56 font-mono uppercase" />
          <Button variant="secondary" type="submit">Search</Button>
        </form>
      </div>
      {message && <div className="mb-4"><Notice kind={message.kind}>{message.text}</Notice></div>}
      {reversing && (
        <Card title="Reverse transfer" className="mb-4">
          <p className="mb-3 text-sm text-slate-600">
            Return {money(reversing.amount)} from {reversing.destination_account_number} to {reversing.source_account_number}. The destination must still hold the money.
          </p>
          <div className="flex flex-wrap gap-2">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (recorded in the ledger and audit trail)" className="max-w-md" />
            <Button variant="danger" onClick={reverse} disabled={reason.trim().length < 5}>Post reversal</Button>
            <Button variant="ghost" onClick={() => setReversing(null)}>Cancel</Button>
          </div>
        </Card>
      )}
      <Card>
        {transfers.data?.length === 0 && <Empty>No transfers match.</Empty>}
        {transfers.data && transfers.data.length > 0 && (
          <Table head={["When", "From", "To", "Amount", "Risk", "Status", ""]}>
            {transfers.data.map((t) => (
              <tr key={t.id}>
                <Td className="text-slate-500">{dateTime(t.created_at)}</Td>
                <Td className="font-mono text-xs">{t.source_account_number}</Td>
                <Td className="font-mono text-xs">{t.destination_account_number}</Td>
                <Td className="num font-medium">{money(t.amount)}</Td>
                <Td>{t.prediction ? <RiskMeter score={t.prediction.risk_score} /> : <span className="text-xs text-slate-400">—</span>}</Td>
                <Td>
                  <Badge value={t.status} />
                  {t.failure_reason && <div className="mt-0.5 max-w-xs truncate text-xs text-slate-500" title={t.failure_reason}>{t.failure_reason}</div>}
                </Td>
                <Td>{isAdmin && t.status === "POSTED" && <Button variant="ghost" onClick={() => { setReversing(t); setMessage(null); }}>Reverse</Button>}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
