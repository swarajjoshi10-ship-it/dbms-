import { useState } from "react";
import { Badge, Button, Card, Empty, Field, Notice, PageHeader, RiskMeter, Select, Table, Td, Textarea } from "../../components/ui";
import { api, type Alert } from "../../lib/api";
import { dateTime, label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const FEATURE_LABELS: Record<string, string> = {
  amount: "Amount (₹)",
  amount_to_avg_ratio: "× sender's average",
  hour_of_day: "Hour of day (IST)",
  is_new_payee: "First transfer to payee",
  sender_account_age_days: "Source account age (days)",
  transfers_last_hour: "Sender transfers in last hour",
  balance_drain_ratio: "Share of balance sent",
  dest_distinct_senders_24h: "Distinct senders to payee (24h)",
  rule_score: "Rule score",
  model_probability: "Random Forest probability",
};

export default function Alerts() {
  const [status, setStatus] = useState("PENDING");
  const [minScore, setMinScore] = useState("0.40");
  const alerts = useApi<Alert[]>(`/fraud/alerts?review_status=${status}&min_score=${minScore}`);
  const [selected, setSelected] = useState<Alert | null>(null);
  const [notes, setNotes] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function open(id: string) {
    setError(null);
    setSelected(await api<Alert>(`/fraud/alerts/${id}`));
  }

  async function review(review_status: string) {
    if (!selected) return;
    try {
      setSelected(await api<Alert>(`/fraud/alerts/${selected.id}/review`, { body: { review_status, notes } }));
      setNotes("");
      setError(null);
      await alerts.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function addNote() {
    if (!selected) return;
    await api(`/fraud/alerts/${selected.id}/notes`, { body: { note } });
    setNote("");
    await open(selected.id);
  }

  const canReview = selected && (selected.review_status === "PENDING" || selected.review_status === "ESCALATED");

  return (
    <>
      <PageHeader title="Fraud alerts" subtitle="Advisory risk scores on posted transfers, highest risk first. Notes are required for every decision." />
      <div className="mb-4 flex flex-wrap gap-3">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-auto">
          {["PENDING", "ESCALATED", "CLEARED", "CONFIRMED_FRAUD", "ALL"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </Select>
        <Select value={minScore} onChange={(e) => setMinScore(e.target.value)} className="w-auto">
          <option value="0.40">Score 0.40 and above</option>
          <option value="0.70">High risk only (0.70+)</option>
          <option value="0">All scores</option>
        </Select>
      </div>
      <div className="grid gap-6 xl:grid-cols-5">
        <Card title={`Queue (${alerts.data?.length ?? 0})`} className="xl:col-span-3">
          {alerts.error && <Notice>{alerts.error}</Notice>}
          {alerts.data?.length === 0 && <Empty>Nothing to review. 🎉</Empty>}
          {alerts.data && alerts.data.length > 0 && (
            <Table head={["Risk", "Amount", "Sender", "To", "Flags", "Status"]}>
              {alerts.data.map((a) => (
                <tr key={a.id} onClick={() => open(a.id)} className={`cursor-pointer hover:bg-slate-50 ${selected?.id === a.id ? "bg-brand-50" : ""}`}>
                  <Td><RiskMeter score={a.risk_score} /></Td>
                  <Td className="num font-medium">{money(a.amount)}</Td>
                  <Td>{a.sender_username}</Td>
                  <Td className="font-mono text-xs">{a.destination_account_number}</Td>
                  <Td wrap className="text-xs text-slate-600">{a.rule_flags.length ? a.rule_flags.map(label).join(", ") : "—"}</Td>
                  <Td><Badge value={a.review_status} /></Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title="Alert detail" className="xl:col-span-2">
          {!selected ? (
            <Empty>Select an alert to see why it was scored.</Empty>
          ) : (
            <div className="space-y-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge value={selected.decision} /> <Badge value={selected.review_status} />
                <span className="text-xs text-slate-500">{selected.model_version} · {dateTime(selected.created_at)}</span>
              </div>
              <div>
                <div className="num text-xl font-semibold">{money(selected.amount)}</div>
                <div className="font-mono text-xs text-slate-500">{selected.source_account_number} → {selected.destination_account_number}</div>
                <div className="text-xs text-slate-500">Transfer status: {label(selected.transfer_status)}</div>
              </div>
              <p className="rounded-lg bg-slate-50 p-3 text-slate-700">{selected.explanation}</p>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                {Object.entries(selected.feature_snapshot).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-slate-500">{FEATURE_LABELS[k] ?? k}</dt>
                    <dd className="num text-right text-slate-800">{v === null ? "—" : typeof v === "number" ? Number(v.toFixed(4)).toString() : String(v)}</dd>
                  </div>
                ))}
              </dl>

              {selected.reviewed_by && (
                <Notice kind="info">Reviewed by {selected.reviewed_by}: {selected.review_notes}</Notice>
              )}
              {error && <Notice>{error}</Notice>}
              {canReview && (
                <div className="space-y-2">
                  <Field label="Decision notes (required)"><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="What did you check, and what did you find?" /></Field>
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={() => review("CLEARED")} disabled={notes.trim().length < 5}>Clear</Button>
                    <Button variant="danger" onClick={() => review("CONFIRMED_FRAUD")} disabled={notes.trim().length < 5}>Confirm fraud</Button>
                    {selected.review_status === "PENDING" && <Button variant="secondary" onClick={() => review("ESCALATED")} disabled={notes.trim().length < 5}>Escalate</Button>}
                  </div>
                </div>
              )}

              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Investigation notes</h3>
                <ul className="space-y-2">
                  {selected.notes?.map((n) => (
                    <li key={n.id} className="rounded-lg border border-slate-100 p-2">
                      <div className="text-xs text-slate-500">{n.author} · {dateTime(n.created_at)}</div>
                      <div>{n.note}</div>
                    </li>
                  ))}
                </ul>
                <div className="mt-2 flex gap-2">
                  <Textarea rows={1} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note" />
                  <Button variant="secondary" onClick={addNote} disabled={!note.trim()}>Add</Button>
                </div>
              </div>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
