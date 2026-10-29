import { useState } from "react";
import { Button, Card, Empty, Field, Input, Notice, PageHeader, Stat, Table, Td } from "../../components/ui";
import { api, type LabRun } from "../../lib/api";
import { dateTime } from "../../lib/format";
import { useApi } from "../../lib/useApi";

const pct = (v: string) => `${(Number(v) * 100).toFixed(1)}%`;

export default function Lab() {
  const runs = useApi<LabRun[]>("/fraud/lab/runs");
  const [samples, setSamples] = useState("2000");
  const [fraudRate, setFraudRate] = useState("0.08");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const latest = runs.data?.[0];

  async function run() {
    setBusy(true);
    try {
      await api("/fraud/lab/runs", { body: { n_samples: Number(samples), fraud_rate: Number(fraudRate) } });
      setError(null);
      await runs.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Fraud Lab" subtitle="Evaluate the Random Forest on a fresh synthetic population it was not trained on." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="New run">
          <div className="space-y-3">
            {error && <Notice>{error}</Notice>}
            <Field label="Transfers to simulate" hint="100 to 20,000"><Input value={samples} onChange={(e) => setSamples(e.target.value)} inputMode="numeric" /></Field>
            <Field label="Share that is fraud" hint="e.g. 0.08 = 8%"><Input value={fraudRate} onChange={(e) => setFraudRate(e.target.value)} inputMode="decimal" /></Field>
            <Button onClick={run} disabled={busy}>{busy ? "Running…" : "Run evaluation"}</Button>
          </div>
        </Card>
        <div className="lg:col-span-2">
          {latest ? (
            <>
              <div className="mb-4 grid gap-4 sm:grid-cols-4">
                <Stat title="Accuracy" value={pct(latest.accuracy)} />
                <Stat title="Precision" value={pct(latest.precision_score)} hint="Flagged that were fraud" />
                <Stat title="Recall" value={pct(latest.recall_score)} hint="Fraud that was flagged" />
                <Stat title="F1" value={pct(latest.f1_score)} />
              </div>
              <Card title="Confusion matrix (latest run, threshold 0.5)">
                <div className="grid max-w-sm grid-cols-3 gap-1 text-center text-sm">
                  <div />
                  <div className="text-xs text-slate-500">Predicted legit</div>
                  <div className="text-xs text-slate-500">Predicted fraud</div>
                  <div className="text-left text-xs text-slate-500">Actual legit</div>
                  <div className="num rounded bg-emerald-50 py-3 font-semibold">{latest.confusion.tn}</div>
                  <div className="num rounded bg-amber-50 py-3 font-semibold">{latest.confusion.fp}</div>
                  <div className="text-left text-xs text-slate-500">Actual fraud</div>
                  <div className="num rounded bg-rose-50 py-3 font-semibold">{latest.confusion.fn}</div>
                  <div className="num rounded bg-emerald-50 py-3 font-semibold">{latest.confusion.tp}</div>
                </div>
              </Card>
            </>
          ) : (
            <Card><Empty>No runs yet.</Empty></Card>
          )}
        </div>
      </div>
      {runs.data && runs.data.length > 0 && (
        <Card title="History" className="mt-6">
          <Table head={["When", "Model", "Samples", "Fraud rate", "Accuracy", "Precision", "Recall", "F1"]}>
            {runs.data.map((r) => (
              <tr key={r.id}>
                <Td className="text-slate-500">{dateTime(r.created_at)}</Td>
                <Td>{r.model_version}</Td>
                <Td className="num">{r.n_samples}</Td>
                <Td className="num">{(r.scenario.fraud_rate * 100).toFixed(1)}%</Td>
                <Td className="num">{pct(r.accuracy)}</Td>
                <Td className="num">{pct(r.precision_score)}</Td>
                <Td className="num">{pct(r.recall_score)}</Td>
                <Td className="num">{pct(r.f1_score)}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      )}
    </>
  );
}
