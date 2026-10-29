import { useState } from "react";
import { Badge, Button, Card, Empty, Field, Notice, PageHeader, Select, Table, Td, Textarea } from "../../components/ui";
import { api, type CaseEvent, type Dispute } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { dateTime, label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

export function CaseTimeline({ events }: { events: CaseEvent[] }) {
  return (
    <ol className="space-y-3 border-l border-slate-200 pl-4">
      {events.map((e) => (
        <li key={e.id} className="relative text-sm">
          <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-brand-600" />
          <div className="text-xs text-slate-500">{label(e.event_type)} · {e.actor ?? "system"} · {dateTime(e.created_at)}</div>
          <div className="text-slate-800">{e.message}</div>
        </li>
      ))}
    </ol>
  );
}

export default function StaffDisputes() {
  const { session } = useAuth();
  const [status, setStatus] = useState("ALL");
  const disputes = useApi<Dispute[]>(`/disputes?status=${status}`);
  const [open, setOpen] = useState<Dispute | null>(null);
  const [comment, setComment] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function act(path: string, body?: unknown) {
    if (!open) return;
    try {
      setOpen(await api<Dispute>(`/disputes/${open.id}/${path}`, { body: body ?? {} }));
      setError(null);
      await disputes.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <PageHeader title="Disputes" subtitle="Customer complaints about transfers. Refunds for upheld disputes are made with an admin reversal." />
      <div className="mb-4">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-auto">
          {["ALL", "OPEN", "INVESTIGATING", "RESOLVED_UPHELD", "RESOLVED_REJECTED"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </Select>
      </div>
      <div className="grid gap-6 xl:grid-cols-5">
        <Card title="Cases" className="xl:col-span-3">
          {disputes.data?.length === 0 && <Empty>No disputes.</Empty>}
          {disputes.data && disputes.data.length > 0 && (
            <Table head={["Opened", "Customer", "Amount", "Reason", "Assignee", "Status"]}>
              {disputes.data.map((d) => (
                <tr key={d.id} onClick={async () => setOpen(await api<Dispute>(`/disputes/${d.id}`))} className={`cursor-pointer hover:bg-slate-50 ${open?.id === d.id ? "bg-brand-50" : ""}`}>
                  <Td className="text-slate-500">{dateTime(d.created_at)}</Td>
                  <Td>{d.customer_name}</Td>
                  <Td className="num">{money(d.amount)}</Td>
                  <Td>{label(d.reason)}</Td>
                  <Td>{d.assigned_staff ?? "—"}</Td>
                  <Td><Badge value={d.status} /></Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        <Card title="Case" className="xl:col-span-2">
          {!open ? (
            <Empty>Select a case.</Empty>
          ) : (
            <div className="space-y-4 text-sm">
              <div className="flex items-center justify-between"><Badge value={open.status} /><span className="text-xs text-slate-500">Transfer {label(open.transfer_status)}</span></div>
              <div>
                <div className="font-medium">{open.customer_name} · {label(open.reason)}</div>
                <div className="num">{money(open.amount)} <span className="font-mono text-xs text-slate-500">to {open.destination_account_number}</span></div>
                <p className="mt-2 rounded-lg bg-slate-50 p-3 text-slate-700">{open.description}</p>
                <p className="mt-1 font-mono text-xs text-slate-400">transfer {open.transfer_request_id}</p>
              </div>
              <CaseTimeline events={open.events} />
              {error && <Notice>{error}</Notice>}
              {!open.status.startsWith("RESOLVED") && (
                <div className="space-y-3 border-t border-slate-100 pt-3">
                  {open.assigned_staff !== session?.user.username && <Button variant="secondary" onClick={() => act("assign")}>Assign to me</Button>}
                  <div className="flex gap-2">
                    <Textarea rows={1} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment" />
                    <Button variant="secondary" onClick={() => { void act("comments", { message: comment }); setComment(""); }} disabled={!comment.trim()}>Add</Button>
                  </div>
                  <Field label="Resolution notes"><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
                  <div className="flex gap-2">
                    <Button onClick={() => act("resolve", { outcome: "RESOLVED_UPHELD", notes })} disabled={notes.trim().length < 5}>Uphold</Button>
                    <Button variant="secondary" onClick={() => act("resolve", { outcome: "RESOLVED_REJECTED", notes })} disabled={notes.trim().length < 5}>Reject</Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
