import { useState } from "react";
import { Badge, Button, Card, Field, Input, Notice, PageHeader, Select, Table, Td } from "../../components/ui";
import { api, type Product } from "../../lib/api";
import { label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const TYPES = ["FIXED_DEPOSIT", "RECURRING_DEPOSIT", "MUTUAL_FUND", "TREASURY_BILL"];
const EMPTY = { name: "", code: "", product_type: "FIXED_DEPOSIT", annual_yield_rate: "", min_amount: "", term_months: "" };

export default function Products() {
  const products = useApi<Product[]>("/products");
  const [form, setForm] = useState(EMPTY);
  const [message, setMessage] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function create() {
    try {
      await api("/products", { body: { ...form, term_months: Number(form.term_months) } });
      setMessage({ kind: "success", text: `Product ${form.code.toUpperCase()} created.` });
      setForm(EMPTY);
      await products.reload();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    }
  }

  async function patch(p: Product, body: Record<string, unknown>) {
    try {
      await api(`/products/${p.id}`, { method: "PATCH", body });
      await products.reload();
    } catch (e) {
      setMessage({ kind: "error", text: (e as Error).message });
    }
  }

  function editRate(p: Product) {
    const rate = window.prompt(`New annual yield for ${p.code} (%)`, p.annual_yield_rate);
    if (rate) void patch(p, { annual_yield_rate: rate });
  }

  return (
    <>
      <PageHeader title="Products" subtitle="The deposit products customers can buy." />
      {message && <div className="mb-4"><Notice kind={message.kind}>{message.text}</Notice></div>}
      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Catalogue" className="xl:col-span-2">
          <Table head={["Code", "Type", "Rate", "Minimum", "Term", "Status", ""]}>
            {products.data?.map((p) => (
              <tr key={p.id}>
                <Td><div className="font-mono text-xs">{p.code}</div><div className="text-xs text-slate-500">{p.name}</div></Td>
                <Td>{label(p.product_type)}</Td>
                <Td className="num">{Number(p.annual_yield_rate).toFixed(2)}%</Td>
                <Td className="num">{money(p.min_amount)}</Td>
                <Td className="num">{p.term_months} mo</Td>
                <Td><Badge value={p.is_active ? "ACTIVE" : "CLOSED"} tone={p.is_active ? "green" : "slate"} /></Td>
                <Td>
                  <div className="flex gap-1">
                    <Button variant="ghost" onClick={() => editRate(p)}>Rate</Button>
                    <Button variant="ghost" onClick={() => patch(p, { is_active: !p.is_active })}>{p.is_active ? "Withdraw" : "Publish"}</Button>
                  </div>
                </Td>
              </tr>
            ))}
          </Table>
        </Card>
        <Card title="New product">
          <div className="space-y-3">
            <Field label="Name"><Input value={form.name} onChange={set("name")} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Code"><Input value={form.code} onChange={set("code")} placeholder="FD-24M-STD" className="font-mono uppercase" /></Field>
              <Field label="Type">
                <Select value={form.product_type} onChange={set("product_type")}>{TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}</Select>
              </Field>
              <Field label="Yield (% a year)"><Input value={form.annual_yield_rate} onChange={set("annual_yield_rate")} inputMode="decimal" /></Field>
              <Field label="Term (months)"><Input value={form.term_months} onChange={set("term_months")} inputMode="numeric" /></Field>
            </div>
            <Field label="Minimum amount (₹)"><Input value={form.min_amount} onChange={set("min_amount")} inputMode="decimal" /></Field>
            <Button onClick={create} disabled={!form.name || !form.code || !form.annual_yield_rate || !form.min_amount || !form.term_months}>Create product</Button>
          </div>
        </Card>
      </div>
    </>
  );
}
