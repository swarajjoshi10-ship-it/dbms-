import { useState } from "react";
import { Button, Card, Empty, Input, PageHeader, Table, Td } from "../../components/ui";
import type { AuditRow } from "../../lib/api";
import { dateTime } from "../../lib/format";
import { useApi } from "../../lib/useApi";

export default function Audit() {
  const [action, setAction] = useState("");
  const [query, setQuery] = useState("");
  const rows = useApi<AuditRow[]>(`/audit?limit=300${query ? `&action=${encodeURIComponent(query)}` : ""}`);

  return (
    <>
      <PageHeader title="Audit trail" subtitle="Append-only: the database refuses UPDATE, DELETE and TRUNCATE on this table." />
      <form onSubmit={(e) => { e.preventDefault(); setQuery(action.trim()); }} className="mb-4 flex gap-2">
        <Input value={action} onChange={(e) => setAction(e.target.value)} placeholder="Filter by action, e.g. TRANSFER_FAILED" className="max-w-xs font-mono uppercase" />
        <Button variant="secondary" type="submit">Filter</Button>
      </form>
      <Card>
        {rows.data?.length === 0 && <Empty>No audit rows.</Empty>}
        {rows.data && rows.data.length > 0 && (
          <Table head={["#", "When", "Actor", "Action", "Entity", "Details", "IP"]}>
            {rows.data.map((r) => (
              <tr key={r.id}>
                <Td className="num text-slate-400">{r.id}</Td>
                <Td className="text-slate-500">{dateTime(r.created_at)}</Td>
                <Td>{r.actor ?? <span className="text-slate-400">system / unknown</span>}</Td>
                <Td className="font-mono text-xs">{r.action}</Td>
                <Td className="text-xs text-slate-600">{r.entity_type} <span className="font-mono text-slate-400">{r.entity_id.slice(0, 8)}</span></Td>
                <Td className="max-w-sm truncate font-mono text-xs text-slate-500" >{Object.keys(r.metadata_json).length ? JSON.stringify(r.metadata_json) : ""}</Td>
                <Td className="text-xs text-slate-500">{r.ip_address}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
