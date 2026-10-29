import { Badge, Button, Card, Notice, PageHeader, Stat, Table, Td } from "../../components/ui";
import type { Reconciliation as Rec } from "../../lib/api";
import { dateTime, label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

export default function Reconciliation() {
  const rec = useApi<Rec>("/admin/reconciliation");
  const r = rec.data;

  return (
    <>
      <PageHeader
        title="Reconciliation"
        subtitle="Proves cached_balance = Σ credits − Σ debits for every account, every posting balances, and the system total is zero."
        actions={<Button variant="secondary" onClick={() => rec.reload()} disabled={rec.loading}>{rec.loading ? "Checking…" : "Run again"}</Button>}
      />
      {rec.error && <Notice>{rec.error}</Notice>}
      {r && (
        <>
          <div className="mb-4">
            <Notice kind={r.ok ? "success" : "error"}>
              {r.ok ? "Books balance. No discrepancies found." : "Discrepancies found. Investigate before posting further corrections."} Checked {dateTime(r.checked_at)}.
            </Notice>
          </div>
          <div className="mb-6 grid gap-4 sm:grid-cols-4">
            <Stat title="Accounts checked" value={r.accounts_checked} />
            <Stat title="Balance discrepancies" value={r.discrepancies} tone={r.discrepancies ? "red" : "green"} />
            <Stat title="Unbalanced postings" value={r.unbalanced_transactions} tone={r.unbalanced_transactions ? "red" : "green"} />
            <Stat title="System total" value={money(r.system_total)} hint="Customer balances + clearing account" tone={Number(r.system_total) === 0 ? "green" : "red"} />
          </div>
          <Card title="Per-account check">
            <Table head={["Account", "Type", "Status", "Cached balance", "Ledger balance", "Difference", "Legs"]}>
              {r.rows.map((row) => (
                <tr key={row.account_number}>
                  <Td className="font-mono text-xs">{row.account_number}</Td>
                  <Td>{label(row.account_type)}</Td>
                  <Td><Badge value={row.status} /></Td>
                  <Td className="num text-right">{money(row.cached_balance)}</Td>
                  <Td className="num text-right">{money(row.ledger_balance)}</Td>
                  <Td className={`num text-right font-medium ${Number(row.discrepancy) === 0 ? "text-emerald-700" : "text-rose-700"}`}>{money(row.discrepancy)}</Td>
                  <Td className="num text-right text-slate-500">{row.leg_count}</Td>
                </tr>
              ))}
            </Table>
          </Card>
        </>
      )}
    </>
  );
}
