import { describe, expect, it } from "vitest";
import { isValidAmount, label, mask, money } from "./format";

describe("format", () => {
  it("uses Indian digit grouping", () => {
    expect(money("150000")).toBe("₹1,50,000.00");
    expect(money(-881500)).toBe("₹-8,81,500.00");
  });

  it("masks account numbers like the database", () => {
    expect(mask("INR-SAV-3BD2762D")).toBe("XXXXXXXXXXXX762D");
  });

  it("validates amounts", () => {
    expect(isValidAmount("2500.50")).toBe(true);
    expect(isValidAmount("0")).toBe(false);
    expect(isValidAmount("1.005")).toBe(false);
    expect(isValidAmount("-5")).toBe(false);
    expect(isValidAmount("abc")).toBe(false);
  });

  it("turns codes into labels", () => {
    expect(label("CONFIRMED_FRAUD")).toBe("Confirmed fraud");
  });
});
