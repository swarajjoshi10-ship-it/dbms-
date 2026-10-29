import { Link } from "react-router-dom";
import { Card, Empty, Notice, PageHeader, Stat } from "../../components/ui";
import { label, money } from "../../lib/format";
import { useApi } from "../../lib/useApi";

interface Summary {
  totals: Record<string, number | string>;
  daily: { day: string; posted: number; failed: number; volume: string }[];
  risk_bands: { decision: string; n: number }[];
}

export default function Overview() {
  const { data, error } = useApi<Summary>("/reports/summary");
  if (error) return <Notice>{error}</Notice>;
  if (!data) return null;
  const t = data.totals;
  const maxVolume = Math.max(1, ...data.daily.map((d) => Number(d.volume)));
  const bandTotal = data.risk_bands.reduce((s, b) => s + b.n, 0) || 1;
  const bandColor: Record<string, string> = { LOW_RISK: "bg-emerald-500", MEDIUM_RISK: "bg-amber-500", HIGH_RISK: "bg-rose-500" };

  return (
    <>
      <PageHeader title="Overview" subtitle="Headline figures computed live from the ledger." />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat title="Customer deposits" value={money(t.customer_liabilities)} hint={`${t.customer_accounts} accounts · ${t.customers} customers`} />
        <Stat title="Posted transfers" value={t.posted_transfers} hint={`${t.failed_transfers} failed · ${t.reversed_transfers} reversed`} tone="green" />
        <Stat title="Alerts to review" value={<Link to="/alerts" className="hover:underline">{t.pending_alerts}</Link>} hint="Risk score 0.40 and above" tone={Number(t.pending_alerts) > 0 ? "amber" : "slate"} />
        <Stat title="Open disputes" value={<Link to="/disputes" className="hover:underline">{t.open_disputes}</Link>} tone={Number(t.open_disputes) > 0 ? "amber" : "slate"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Transfer volume, last 14 days" className="lg:col-span-2">
          {data.daily.length === 0 ? (
            <Empty>No transfers in the last 14 days.</Empty>
          ) : (
            <div className="space-y-2">
              {data.daily.map((d) => (
                <div key={d.day} className="grid grid-cols-[6rem_1fr_7rem] items-center gap-3 text-sm">
                  <span className="text-slate-500">{new Date(d.day).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</span>
                  <div className="h-3 rounded bg-slate-100">
                    <div className="h-3 rounded bg-brand-600" style={{ width: `${(Number(d.volume) / maxVolume) * 100}%` }} />
                  </div>
                  <span className="num text-right text-slate-700">{money(d.volume)}</span>
                </div>
              ))}
              <p className="pt-2 text-xs text-slate-500">Posted and later-reversed transfers, by day (IST).</p>
            </div>
          )}
        </Card>
        <Card title="Fraud scores by risk band">
          {data.risk_bands.length === 0 ? (
            <Empty>No transfers scored yet.</Empty>
          ) : (
            <div className="space-y-3">
              {data.risk_bands.map((b) => (
                <div key={b.decision}>
                  <div className="mb-1 flex justify-between text-sm"><span>{label(b.decision)}</span><span className="num text-slate-600">{b.n}</span></div>
                  <div className="h-2 rounded bg-slate-100"><div className={`h-2 rounded ${bandColor[b.decision]}`} style={{ width: `${(b.n / bandTotal) * 100}%` }} /></div>
                </div>
              ))}
              <p className="pt-1 text-xs text-slate-500">Scores are advisory. Staff decide every outcome.</p>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
