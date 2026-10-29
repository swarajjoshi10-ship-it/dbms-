import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Notice, PageHeader, Select, Table, Td } from "../../components/ui";
import { api, type Account, type CustomerProfile } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

export default function Customers() {
  const { session } = useAuth();
  const isAdmin = session?.user.role === "ADMIN";
  const accounts = useApi<Account[]>("/admin/accounts");
  const customers = useApi<CustomerProfile[]>("/admin/customers");
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  async function setStatus(a: Account, status: string) {
    const reason = window.prompt(`Reason for setting ${a.account_number} to ${status}:`);
    if (!reason) return;
    try {
      await api(`/admin/accounts/${a.id}/status`, { body: { status, reason } });
      setMessage({ kind: "success", text: `${a.account_number} is now ${label(status)}.` });
      await accounts.reload();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    }
  }

  async function setKyc(c: CustomerProfile, kyc_status: string) {
    try {
      await api(`/admin/customers/${c.id}/kyc`, { body: { kyc_status } });
      setMessage({ kind: "success", text: `KYC for ${c.full_name} set to ${label(kyc_status)}.` });
      await Promise.all([customers.reload(), accounts.reload()]);
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    }
  }

  return (
    <>
      <PageHeader title="Customers & accounts" subtitle="KYC review and account status. Balances change only through ledger postings." />
      {message && <div className="mb-4"><Notice kind={message.kind}>{message.text}</Notice></div>}
      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Accounts" className="xl:col-span-2">
          <Table head={["Account", "Owner", "Type", "Balance", "Status", ""]}>
            {accounts.data?.map((a) => (
              <tr key={a.id}>
                <Td><Link to={`/statement?account=${a.id}`} className="font-mono text-xs text-brand-700 hover:underline">{a.account_number}</Link></Td>
                <Td>{a.owner_name ?? <span className="text-slate-400">Bank internal</span>}</Td>
                <Td>{label(a.account_type)}</Td>
                <Td className={`num text-right ${Number(a.cached_balance) < 0 ? "text-rose-700" : ""}`}>{money(a.cached_balance)}</Td>
                <Td><Badge value={a.status} /></Td>
                <Td>
                  {isAdmin && a.account_type !== "INTERNAL_CLEARING" && a.status !== "CLOSED" && (
                    <div className="flex gap-1">
                      {a.status === "ACTIVE" ? (
                        <Button variant="ghost" onClick={() => setStatus(a, "FROZEN")}>Freeze</Button>
                      ) : (
                        <Button variant="ghost" onClick={() => setStatus(a, "ACTIVE")}>Unfreeze</Button>
                      )}
                      {Number(a.cached_balance) === 0 && <Button variant="ghost" onClick={() => setStatus(a, "CLOSED")}>Close</Button>}
                    </div>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        </Card>
        <Card title="KYC review">
          <ul className="divide-y divide-slate-100">
            {customers.data?.map((c) => (
              <li key={c.id} className="flex items-center justify-between gap-3 py-2.5">
                <div>
                  <div className="text-sm font-medium">{c.full_name}</div>
                  <div className="text-xs text-slate-500">PAN {c.pan_number ?? "missing"} · {c.phone ?? "no phone"}</div>
                </div>
                <Select value={c.kyc_status} onChange={(e) => setKyc(c, e.target.value)} className="w-32 py-1">
                  {["PENDING", "VERIFIED", "REJECTED"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
                </Select>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
