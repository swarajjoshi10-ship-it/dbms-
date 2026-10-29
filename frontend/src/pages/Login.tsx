import { useState, type FormEvent } from "react";
import { Button, Field, Input, Notice } from "../components/ui";
import { useAuth } from "../lib/auth";

const DEMO = [
  { username: "rahul_sharma", role: "Customer" },
  { username: "sneha_kapoor", role: "Customer" },
  { username: "priya_investigator", role: "Staff" },
  { username: "admin_system", role: "Admin" },
];

export default function Login() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ username: "", password: "", email: "", full_name: "", phone: "", pan_number: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(form.username.trim(), form.password);
      else await register(form);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-brand-800 p-10 text-emerald-50 lg:flex">
        <div className="flex items-center gap-2 text-lg font-semibold text-white">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-white/15">₹</span>FinLedger-AI
        </div>
        <div>
          <h1 className="text-3xl font-semibold leading-tight text-white">An auditable ledger with advisory fraud detection.</h1>
          <ul className="mt-6 space-y-2 text-sm text-emerald-100">
            <li>Every rupee moves as a balanced debit and credit, checked by PostgreSQL at commit.</li>
            <li>The ledger and audit trail are append-only. Corrections are new postings.</li>
            <li>The fraud model scores transfers. People decide what happens next.</li>
          </ul>
        </div>
        <p className="text-xs text-emerald-200">VIT Vellore · BCSE302P Database Systems</p>
      </div>

      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <h2 className="text-xl font-semibold text-slate-900">{mode === "login" ? "Sign in" : "Open an account"}</h2>
          <p className="mt-1 text-sm text-slate-500">
            {mode === "login" ? "New customer? " : "Already registered? "}
            <button type="button" className="font-medium text-brand-700 hover:underline" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
              {mode === "login" ? "Register" : "Sign in"}
            </button>
          </p>

          <form onSubmit={submit} className="mt-6 space-y-3">
            {error && <Notice>{error}</Notice>}
            <Field label="Username"><Input value={form.username} onChange={set("username")} autoComplete="username" required /></Field>
            {mode === "register" && (
              <>
                <Field label="Full name"><Input value={form.full_name} onChange={set("full_name")} required /></Field>
                <Field label="Email"><Input type="email" value={form.email} onChange={set("email")} required /></Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Phone (optional)"><Input value={form.phone} onChange={set("phone")} placeholder="+91-98…" /></Field>
                  <Field label="PAN (optional)"><Input value={form.pan_number} onChange={set("pan_number")} placeholder="ABCDE1234F" maxLength={10} /></Field>
                </div>
              </>
            )}
            <Field label="Password" hint={mode === "register" ? "At least 8 characters." : undefined}>
              <Input type="password" value={form.password} onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} required />
            </Field>
            <Button type="submit" disabled={busy} className="w-full">{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</Button>
          </form>

          {mode === "login" && (
            <div className="mt-8 rounded-lg border border-slate-200 bg-white p-4 text-xs text-slate-600">
              <div className="mb-2 font-medium text-slate-700">Demo users (password from the seed script)</div>
              <div className="flex flex-wrap gap-1.5">
                {DEMO.map((d) => (
                  <button key={d.username} type="button" onClick={() => setForm({ ...form, username: d.username })} className="rounded-md bg-slate-100 px-2 py-1 hover:bg-slate-200">
                    {d.username} <span className="text-slate-400">· {d.role}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
