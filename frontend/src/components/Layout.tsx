import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import type { Role } from "../lib/api";
import { useAuth } from "../lib/auth";

const NAV: Record<Role, { to: string; label: string }[]> = {
  CUSTOMER: [
    { to: "/", label: "Accounts" },
    { to: "/transfer", label: "Send money" },
    { to: "/statement", label: "Statement" },
    { to: "/invest", label: "Invest" },
    { to: "/disputes", label: "Disputes" },
  ],
  STAFF: [
    { to: "/", label: "Overview" },
    { to: "/alerts", label: "Fraud alerts" },
    { to: "/graph", label: "Money-flow graph" },
    { to: "/disputes", label: "Disputes" },
    { to: "/transfers", label: "Transfers" },
    { to: "/customers", label: "Customers & accounts" },
    { to: "/lab", label: "Fraud Lab" },
    { to: "/audit", label: "Audit trail" },
  ],
  ADMIN: [],
};
NAV.ADMIN = [...NAV.STAFF.slice(0, 6), { to: "/reconciliation", label: "Reconciliation" }, { to: "/products", label: "Products" }, ...NAV.STAFF.slice(6)];

export default function Layout() {
  const { session, logout } = useAuth();
  const [open, setOpen] = useState(false);
  if (!session) return null;
  const { user, customer } = session;

  const links = (
    <nav className="flex flex-col gap-0.5">
      {NAV[user.role].map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            `rounded-lg px-3 py-2 text-sm font-medium ${isActive ? "bg-brand-50 text-brand-800" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"}`
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen md:flex">
      <aside className={`${open ? "block" : "hidden"} border-b border-slate-200 bg-white p-4 md:sticky md:top-0 md:block md:h-screen md:w-60 md:shrink-0 md:border-b-0 md:border-r`}>
        <div className="mb-6 hidden items-center gap-2 md:flex">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand-700 font-bold text-white">₹</div>
          <div>
            <div className="text-sm font-semibold text-slate-900">FinLedger-AI</div>
            <div className="text-xs text-slate-500">{user.role === "CUSTOMER" ? "Retail banking" : user.role === "ADMIN" ? "Operations admin" : "Compliance"}</div>
          </div>
        </div>
        {links}
        <div className="mt-6 border-t border-slate-100 pt-4 text-xs text-slate-500">
          <div className="font-medium text-slate-700">{customer?.full_name ?? user.username}</div>
          <div>{user.email}</div>
          <button onClick={logout} className="mt-3 text-sm font-medium text-brand-700 hover:underline">Sign out</button>
        </div>
      </aside>
      <div className="flex-1">
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
          <div className="flex items-center gap-2 font-semibold"><span className="grid h-7 w-7 place-items-center rounded-md bg-brand-700 text-white">₹</span>FinLedger-AI</div>
          <button onClick={() => setOpen(!open)} className="rounded-md border border-slate-300 px-2.5 py-1 text-sm" aria-expanded={open}>Menu</button>
        </div>
        <main className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
