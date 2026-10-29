import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Empty, Field, Input, Notice, PageHeader, Select, Table, Td } from "../../components/ui";
import { api, type Account, type Transfer } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { dateTime, isValidAmount, label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

export default function Accounts() {
  const { session } = useAuth();
  const accounts = useApi<Account[]>("/accounts");
  const transfers = useApi<Transfer[]>("/transfers?limit=8");
  const [depositTo, setDepositTo] = useState("");
  const [amount, setAmount] = useState("");
  const [newType, setNewType] = useState("CURRENT");
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const list = accounts.data ?? [];
  const spendable = list.filter((a) => a.account_type === "SAVINGS" || a.account_type === "CURRENT");
  const total = list.reduce((sum, a) => sum + Number(a.cached_balance), 0);
  const ownIds = new Set(list.map((a) => a.id));

  async function deposit() {
    const target = depositTo || spendable[0]?.id;
    if (!target || !isValidAmount(amount)) return setMessage({ kind: "error", text: "Enter a positive amount with at most two decimals." });
    setBusy(true);
    try {
      await api(`/accounts/${target}/deposit`, { body: { amount } });
      setMessage({ kind: "success", text: `${money(amount)} deposited. It was posted as a balanced entry against the bank's clearing account.` });
      setAmount("");
      await accounts.reload();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function openAccount() {
    setBusy(true);
    try {
      const acc = await api<Account>("/accounts", { body: { account_type: newType } });
      setMessage({ kind: "success", text: `Opened ${label(acc.account_type)} account ${acc.account_number}.` });
      await accounts.reload();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={`Welcome, ${session?.customer?.full_name.split(" ")[0] ?? ""}`}
        subtitle={`KYC status: ${label(session?.customer?.kyc_status ?? "PENDING")}`}
        actions={<Link to="/transfer"><Button>Send money</Button></Link>}
      />
      {accounts.error && <Notice>{accounts.error}</Notice>}

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((a) => (
          <div key={a.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wide text-slate-500">{label(a.account_type)}</span>
              <Badge value={a.status} />
            </div>
            <div className="num mt-2 text-2xl font-semibold text-slate-900">{money(a.cached_balance)}</div>
            <div className="mt-1 font-mono text-xs text-slate-500">{a.account_number}</div>
            <Link to={`/statement?account=${a.id}`} className="mt-3 inline-block text-sm font-medium text-brand-700 hover:underline">View statement</Link>
          </div>
        ))}
        <div className="rounded-xl border border-dashed border-slate-300 p-5">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Total across accounts</div>
          <div className="num mt-2 text-2xl font-semibold text-slate-900">{money(total)}</div>
          <div className="mt-3 flex gap-2">
            <Select value={newType} onChange={(e) => setNewType(e.target.value)} className="w-auto">
              <option value="CURRENT">Current</option>
              <option value="SAVINGS">Savings</option>
            </Select>
            <Button variant="secondary" onClick={openAccount} disabled={busy}>Open account</Button>
          </div>
        </div>
      </div>

      {message && <div className="mb-4"><Notice kind={message.kind}>{message.text}</Notice></div>}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Add a demo deposit">
          <div className="space-y-3">
            <Field label="Into account">
              <Select value={depositTo} onChange={(e) => setDepositTo(e.target.value)}>
                {spendable.map((a) => <option key={a.id} value={a.id}>{a.account_number} · {money(a.cached_balance)}</option>)}
              </Select>
            </Field>
            <Field label="Amount (₹)" hint="Up to ₹1,00,000 per deposit. This simulates cash coming in from outside the bank.">
              <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="5000.00" />
            </Field>
            <Button onClick={deposit} disabled={busy || spendable.length === 0}>Deposit</Button>
          </div>
        </Card>

        <Card title="Recent transfers" className="lg:col-span-2">
          {transfers.data && transfers.data.length === 0 && <Empty>No transfers yet.</Empty>}
          {transfers.data && transfers.data.length > 0 && (
            <Table head={["When", "From / to", "Amount", "Status"]}>
              {transfers.data.map((t) => {
                const outgoing = ownIds.has(t.source_account_id);
                // A FAILED transfer moved no money, so it gets no sign.
                const amountStyle = t.status === "FAILED" ? "text-slate-400 line-through" : outgoing ? "text-slate-900" : "text-emerald-700";
                const sign = t.status === "FAILED" ? "" : outgoing ? "−" : "+";
                return (
                  <tr key={t.id}>
                    <Td className="text-slate-500">{dateTime(t.created_at)}</Td>
                    <Td><span className="font-mono text-xs">{outgoing ? `to ${t.destination_account_number}` : `from ${t.source_account_number}`}</span></Td>
                    <Td className={`num font-medium ${amountStyle}`}>{sign}{money(t.amount)}</Td>
                    <Td><Badge value={t.status} /></Td>
                  </tr>
                );
              })}
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
