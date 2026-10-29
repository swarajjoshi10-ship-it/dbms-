import { useState } from "react";
import { Badge, Button, Card, Empty, Field, Notice, PageHeader, Select, Table, Td, Textarea } from "../../components/ui";
import { api, type Account, type Dispute, type Transfer } from "../../lib/api";
import { dateTime, label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { CaseTimeline } from "../staff/Disputes";

const REASONS = ["UNAUTHORIZED", "WRONG_RECIPIENT", "WRONG_AMOUNT", "SCAM", "OTHER"];

export default function CustomerDisputes() {
  const accounts = useApi<Account[]>("/accounts");
  const transfers = useApi<Transfer[]>("/transfers?status=POSTED&limit=100");
  const disputes = useApi<Dispute[]>("/disputes");
  const [transferId, setTransferId] = useState("");
  const [reason, setReason] = useState("UNAUTHORIZED");
  const [description, setDescription] = useState("");
  const [open, setOpen] = useState<Dispute | null>(null);
  const [comment, setComment] = useState("");
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  const ownIds = new Set((accounts.data ?? []).map((a) => a.id));
  const sent = (transfers.data ?? []).filter((t) => ownIds.has(t.source_account_id));

  async function file() {
    try {
      const d = await api<Dispute>("/disputes", { body: { transfer_request_id: transferId || sent[0]?.id, reason, description } });
      setMessage({ kind: "success", text: "Dispute opened. A compliance investigator will pick it up." });
      setDescription("");
      setOpen(d);
      await disputes.reload();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    }
  }

  async function addComment() {
    if (!open) return;
    try {
      setOpen(await api<Dispute>(`/disputes/${open.id}/comments`, { body: { message: comment } }));
      setComment("");
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    }
  }

  return (
    <>
      <PageHeader title="Disputes" subtitle="Raise a complaint about a transfer you sent and follow the case." />
      {message && <div className="mb-4"><Notice kind={message.kind}>{message.text}</Notice></div>}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Open a dispute">
          {sent.length === 0 ? (
            <Empty>You have no posted transfers to dispute.</Empty>
          ) : (
            <div className="space-y-3">
              <Field label="Transfer">
                <Select value={transferId} onChange={(e) => setTransferId(e.target.value)}>
                  {sent.map((t) => <option key={t.id} value={t.id}>{money(t.amount)} to {t.destination_account_number} · {dateTime(t.created_at)}</option>)}
                </Select>
              </Field>
              <Field label="Reason">
                <Select value={reason} onChange={(e) => setReason(e.target.value)}>
                  {REASONS.map((r) => <option key={r} value={r}>{label(r)}</option>)}
                </Select>
              </Field>
              <Field label="What happened?" hint="At least 10 characters.">
                <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
              </Field>
              <Button onClick={file} disabled={description.trim().length < 10}>Submit dispute</Button>
            </div>
          )}
        </Card>

        <Card title="My disputes" className="lg:col-span-2">
          {disputes.data?.length === 0 ? (
            <Empty>No disputes.</Empty>
          ) : (
            <Table head={["Opened", "Transfer", "Reason", "Status", ""]}>
              {disputes.data?.map((d) => (
                <tr key={d.id}>
                  <Td className="text-slate-500">{dateTime(d.created_at)}</Td>
                  <Td><span className="num">{money(d.amount)}</span> <span className="font-mono text-xs text-slate-500">to {d.destination_account_number}</span></Td>
                  <Td>{label(d.reason)}</Td>
                  <Td><Badge value={d.status} /></Td>
                  <Td><Button variant="ghost" onClick={async () => setOpen(await api<Dispute>(`/disputes/${d.id}`))}>Open</Button></Td>
                </tr>
              ))}
            </Table>
          )}
          {open && (
            <div className="mt-5 border-t border-slate-100 pt-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold">Case timeline</h3>
                <Badge value={open.status} />
              </div>
              <CaseTimeline events={open.events} />
              {!open.status.startsWith("RESOLVED") && (
                <div className="mt-3 flex gap-2">
                  <Textarea rows={1} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Add information for the investigator" />
                  <Button onClick={addComment} disabled={!comment.trim()}>Send</Button>
                </div>
              )}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
