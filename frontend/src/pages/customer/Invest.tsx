import { useState } from "react";
import { Badge, Button, Card, Empty, Field, Input, Notice, PageHeader, Select, Table, Td } from "../../components/ui";
import { api, type Account, type Investment, type Product } from "../../lib/api";
import { date, isValidAmount, label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

export default function Invest() {
  const products = useApi<Product[]>("/products");
  const accounts = useApi<Account[]>("/accounts");
  const investments = useApi<Investment[]>("/investments");
  const [selected, setSelected] = useState<Product | null>(null);
  const [funding, setFunding] = useState("");
  const [amount, setAmount] = useState("");
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const spendable = (accounts.data ?? []).filter((a) => (a.account_type === "SAVINGS" || a.account_type === "CURRENT") && a.status === "ACTIVE");
  const projected = selected && isValidAmount(amount)
    ? Number(amount) * (1 + (Number(selected.annual_yield_rate) / 100) * (selected.term_months / 12))
    : null;

  async function invest() {
    if (!selected) return;
    if (!isValidAmount(amount)) return setMessage({ kind: "error", text: "Enter a valid amount." });
    setBusy(true);
    try {
      const inv = await api<Investment>("/investments", { body: { product_id: selected.id, funding_account_id: funding || spendable[0]?.id, amount } });
      setMessage({ kind: "success", text: `Invested ${money(inv.principal)} in ${inv.product_code}. Matures on ${date(inv.maturity_date)} at ${money(inv.expected_maturity_value)}.` });
      setAmount("");
      setSelected(null);
      await Promise.all([investments.reload(), accounts.reload()]);
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Invest" subtitle="Simulated deposit products. A purchase is an INVESTMENT_PURCHASE posting into your investment account." />
      {message && <div className="mb-4"><Notice kind={message.kind}>{message.text}</Notice></div>}

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {products.data?.map((p) => (
          <button
            key={p.id}
            onClick={() => { setSelected(p); setMessage(null); }}
            className={`rounded-xl border bg-white p-5 text-left shadow-sm transition hover:border-brand-600 ${selected?.id === p.id ? "border-brand-600 ring-2 ring-brand-100" : "border-slate-200"}`}
          >
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label(p.product_type)}</div>
            <div className="mt-1 font-semibold text-slate-900">{p.name}</div>
            <div className="num mt-3 text-2xl font-semibold text-brand-700">{Number(p.annual_yield_rate).toFixed(2)}%</div>
            <div className="mt-1 text-xs text-slate-500">{p.term_months} months · minimum {money(p.min_amount)}</div>
          </button>
        ))}
      </div>

      {selected && (
        <Card title={`Invest in ${selected.code}`} className="mb-6">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Pay from">
              <Select value={funding} onChange={(e) => setFunding(e.target.value)}>
                {spendable.map((a) => <option key={a.id} value={a.id}>{a.account_number} · {money(a.cached_balance)}</option>)}
              </Select>
            </Field>
            <Field label="Amount (₹)" hint={`Minimum ${money(selected.min_amount)}`}>
              <Input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
            <div className="flex flex-col justify-end">
              <div className="mb-2 text-sm text-slate-600">Projected at maturity: <span className="num font-semibold text-slate-900">{projected ? money(projected.toFixed(2)) : "—"}</span></div>
              <Button onClick={invest} disabled={busy}>Confirm investment</Button>
            </div>
          </div>
        </Card>
      )}

      <Card title="My investments">
        {investments.data?.length === 0 ? (
          <Empty>No investments yet.</Empty>
        ) : (
          <Table head={["Product", "Principal", "Rate", "Started", "Matures", "Maturity value", "Status"]}>
            {investments.data?.map((i) => (
              <tr key={i.id}>
                <Td><div className="font-medium">{i.product_name}</div><div className="text-xs text-slate-500">{i.product_code}</div></Td>
                <Td className="num">{money(i.principal)}</Td>
                <Td className="num">{Number(i.annual_yield_rate).toFixed(2)}%</Td>
                <Td>{date(i.start_date)}</Td>
                <Td>{date(i.maturity_date)}</Td>
                <Td className="num font-medium">{money(i.expected_maturity_value)}</Td>
                <Td><Badge value={i.status} /></Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
