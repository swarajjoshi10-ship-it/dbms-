import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import "./index.css";
import { AuthProvider, useAuth } from "./lib/auth";
import Accounts from "./pages/customer/Accounts";
import CustomerDisputes from "./pages/customer/Disputes";
import Invest from "./pages/customer/Invest";
import Statement from "./pages/customer/Statement";
import Transfer from "./pages/customer/Transfer";
import Login from "./pages/Login";
import Alerts from "./pages/staff/Alerts";
import Audit from "./pages/staff/Audit";
import Customers from "./pages/staff/Customers";
import StaffDisputes from "./pages/staff/Disputes";
import Graph from "./pages/staff/Graph";
import Lab from "./pages/staff/Lab";
import Overview from "./pages/staff/Overview";
import Products from "./pages/staff/Products";
import Reconciliation from "./pages/staff/Reconciliation";
import Transfers from "./pages/staff/Transfers";

function AppRoutes() {
  const { session, loading } = useAuth();
  if (loading) return <div className="grid min-h-screen place-items-center text-sm text-slate-500">Loading…</div>;
  if (!session) return <Login />;

  const role = session.user.role;
  return (
    <Routes>
      <Route element={<Layout />}>
        {role === "CUSTOMER" ? (
          <>
            <Route index element={<Accounts />} />
            <Route path="transfer" element={<Transfer />} />
            <Route path="statement" element={<Statement />} />
            <Route path="invest" element={<Invest />} />
            <Route path="disputes" element={<CustomerDisputes />} />
          </>
        ) : (
          <>
            <Route index element={<Overview />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="graph" element={<Graph />} />
            <Route path="disputes" element={<StaffDisputes />} />
            <Route path="transfers" element={<Transfers />} />
            <Route path="customers" element={<Customers />} />
            <Route path="statement" element={<Statement />} />
            <Route path="lab" element={<Lab />} />
            <Route path="audit" element={<Audit />} />
            {role === "ADMIN" && <Route path="reconciliation" element={<Reconciliation />} />}
            {role === "ADMIN" && <Route path="products" element={<Products />} />}
          </>
        )}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
