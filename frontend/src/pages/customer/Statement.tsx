import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Button, Card, Empty, Notice, PageHeader, Select, Table, Td } from "../../components/ui";
import type { Account, StatementLine } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { dateTime, label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const PAGE = 25;

/** Account statement with running balance. Customers pick their own accounts; staff arrive with ?account=. */
export default function Statement() {
  const { session } = useAuth();
  const isCustomer = session?.user.role === "CUSTOMER";
  const [params, setParams] = useSearchParams();
  const accounts = useApi<Account[]>(isCustomer ? "/accounts" : "/admin/accounts");
  const [page, setPage] = useState(0);

  const accountId = params.get("account") ?? accounts.data?.[0]?.id ?? null;
  const statement = useApi<{ account: Account; total: number; lines: StatementLine[] }>(
    accountId ? `/accounts/${accountId}/statement?limit=${PAGE}&offset=${page * PAGE}` : null,
  );
  const s = statement.data;
  const pages = s ? Math.max(1, Math.ceil(s.total / PAGE)) : 1;

  return (
    <>
      <PageHeader title="Statement" subtitle="Every leg posted to the account, newest first, with the balance after each one." />
      <div className="mb-4 max-w-md">
        <Select value={accountId ?? ""} onChange={(e) => { setPage(0); setParams({ account: e.target.value }); }}>
          {accounts.data?.map((a) => (
            <option key={a.id} value={a.id}>{a.account_number} · {label(a.account_type)}{a.owner_name ? ` · ${a.owner_name}` : ""}</option>
          ))}
        </Select>
      </div>
      {statement.error && <Notice>{statement.error}</Notice>}
      {s && (
        <Card title={`${s.account.account_number} · balance ${money(s.account.cached_balance)}`} actions={<Badge value={s.account.status} />}>
          {s.lines.length === 0 ? (
            <Empty>No entries yet.</Empty>
          ) : (
            <Table head={["Date", "Description", "Counterparty", "Debit", "Credit", "Balance"]}>
              {s.lines.map((l) => (
                <tr key={l.entry_id}>
                  <Td className="text-slate-500">{dateTime(l.created_at)}</Td>
                  <Td>
                    <div className="font-medium text-slate-800">{l.description}</div>
                    <div className="text-xs text-slate-500">{label(l.transaction_type)}</div>
                  </Td>
                  <Td className="font-mono text-xs text-slate-600">{l.counterparty}</Td>
                  <Td className="num text-right">{l.entry_type === "DEBIT" ? money(l.amount) : ""}</Td>
                  <Td className="num text-right text-emerald-700">{l.entry_type === "CREDIT" ? money(l.amount) : ""}</Td>
                  <Td className="num text-right font-medium">{money(l.running_balance)}</Td>
                </tr>
              ))}
            </Table>
          )}
          {pages > 1 && (
            <div className="mt-4 flex items-center justify-end gap-2 text-sm text-slate-500">
              <Button variant="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>Newer</Button>
              <span>Page {page + 1} of {pages}</span>
              <Button variant="secondary" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Older</Button>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
