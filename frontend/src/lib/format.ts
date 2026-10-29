/** Indian digit grouping (1,50,000.00), matching TO_CHAR(..., 'FM99,99,99,990.00') in the database. */
const inr = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function money(value: string | number): string {
  const n = typeof value === "string" ? Number(value) : value;
  return `₹${inr.format(n)}`;
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function date(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function label(code: string): string {
  return code.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

/** Same rule as the API and SQL: LPAD(RIGHT(n, 4), LENGTH(n), 'X'). */
export function mask(accountNumber: string): string {
  return accountNumber.slice(-4).padStart(accountNumber.length, "X");
}

/** Amount entered by a user: positive, at most two decimal places. */
export function isValidAmount(text: string): boolean {
  return /^\d{1,13}(\.\d{1,2})?$/.test(text.trim()) && Number(text) > 0;
}
