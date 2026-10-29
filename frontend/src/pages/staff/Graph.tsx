import { useState } from "react";
import { Badge, Button, Card, Empty, Notice, PageHeader, Select } from "../../components/ui";
import { api, type GraphFinding } from "../../lib/api";
import { dateTime, label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const EXPLAIN: Record<string, string> = {
  CYCLE: "Money left an account and came back to it through other accounts within 7 days (found with a recursive CTE).",
  FAN_IN: "One account received money from four or more different accounts in 24 hours, a common mule pattern.",
  RAPID_PASS_THROUGH: "An account sent on 80% or more of a large incoming transfer to other customers within an hour.",
};

export default function Graph() {
  const [status, setStatus] = useState("OPEN");
  const findings = useApi<GraphFinding[]>(`/graph/findings?status=${status}`);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function scan() {
    setBusy(true);
    try {
      const created = await api<GraphFinding[]>("/graph/scan", { body: {} });
      setMessage(created.length ? `${created.length} new pattern(s) found.` : "Scan complete. No new patterns.");
      await findings.reload();
    } finally {
      setBusy(false);
    }
  }

  async function setFindingStatus(f: GraphFinding, next: string) {
    await api(`/graph/findings/${f.id}`, { method: "PATCH", body: { status: next } });
    await findings.reload();
  }

  return (
    <>
      <PageHeader
        title="Money-flow graph"
        subtitle="Patterns across accounts that a per-transfer score cannot see."
        actions={<Button onClick={scan} disabled={busy}>{busy ? "Scanning…" : "Run graph scan"}</Button>}
      />
      {message && <div className="mb-4"><Notice kind="info">{message}</Notice></div>}
      <div className="mb-4">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-auto">
          {["OPEN", "CONFIRMED", "DISMISSED", "ALL"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </Select>
      </div>
      {findings.data?.length === 0 && <Card><Empty>No findings. Run a scan after some transfers.</Empty></Card>}
      <div className="grid gap-4 lg:grid-cols-2">
        {findings.data?.map((f) => (
          <Card key={f.id} title={label(f.finding_type)} actions={<div className="flex gap-1.5"><Badge value={f.severity} /><Badge value={f.status} /></div>}>
            <p className="text-sm text-slate-600">{EXPLAIN[f.finding_type]}</p>
            <div className="mt-3 flex flex-wrap items-center gap-1.5 font-mono text-xs">
              {f.involved_account_numbers.map((n, i) => (
                <span key={n} className="flex items-center gap-1.5">
                  <span className={`rounded px-1.5 py-0.5 ${n === f.primary_account_number ? "bg-rose-100 text-rose-800" : "bg-slate-100"}`}>{n}</span>
                  {f.finding_type === "CYCLE" && i < f.involved_account_numbers.length - 1 && <span className="text-slate-400">·</span>}
                </span>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between text-sm">
              <span className="num">Amount involved: <strong>{money(f.total_amount)}</strong></span>
              <span className="text-xs text-slate-500">{dateTime(f.created_at)}</span>
            </div>
            {f.status === "OPEN" && (
              <div className="mt-3 flex gap-2">
                <Button variant="danger" onClick={() => setFindingStatus(f, "CONFIRMED")}>Confirm</Button>
                <Button variant="secondary" onClick={() => setFindingStatus(f, "DISMISSED")}>Dismiss</Button>
              </div>
            )}
          </Card>
        ))}
      </div>
    </>
  );
}
