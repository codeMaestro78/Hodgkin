import { describe, expect, it } from "vitest";
import {
  clearResearchDraft,
  emptyResearchDraft,
  MAX_REQUIREMENTS_TEXT,
  parseReportRequirements,
  readResearchDraft,
  researchDraftAccount,
  researchDraftKey,
  writeResearchDraft,
} from "../lib/research-draft";

function memoryStorage() {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
    removeItem: (key: string) => {
      values.delete(key);
    },
  };
  return { values, storage: () => storage };
}
const draft = {
  ...emptyResearchDraft,
  question: "Compare research tools",
  requirementsText: "Discuss costs\nCover risks",
  requireApproval: false,
};

describe("report requirements", () => {
  it("trims lines, ignores blanks, handles CRLF and preserves order", () => {
    expect(
      parseReportRequirements(" costs \r\n\r\n risks\r evidence "),
    ).toEqual(["costs", "risks", "evidence"]);
    expect(parseReportRequirements("  \n ")).toEqual([]);
  });
  it("accepts the exact count and per-line bounds", () => {
    const lines = Array.from({ length: 20 }, () => "a".repeat(500));
    expect(parseReportRequirements(lines.join("\n"))).toEqual(lines);
  });
  it("rejects excess lines/characters without truncating", () => {
    expect(() =>
      parseReportRequirements(Array(21).fill("a").join("\n")),
    ).toThrow("20");
    expect(() => parseReportRequirements("a".repeat(501))).toThrow("500");
    expect(() =>
      parseReportRequirements("a".repeat(MAX_REQUIREMENTS_TEXT + 1)),
    ).toThrow();
  });
});

describe("account-scoped session draft", () => {
  it("round trips all fields and isolates accounts", () => {
    const { storage } = memoryStorage();
    expect(writeResearchDraft("account-a", draft, storage)).toBe(true);
    expect(readResearchDraft("account-a", storage)).toEqual(draft);
    expect(readResearchDraft("account-b", storage)).toBeNull();
    expect(researchDraftKey("a:b")).not.toBe(researchDraftKey("a%3Ab"));
    expect(researchDraftKey("")).toBeNull();
  });
  it("checks the embedded account and schema version", () => {
    const { storage } = memoryStorage();
    const key = researchDraftKey("account-a")!;
    for (const record of [
      { version: 1, accountId: "account-b", draft },
      { version: 2, accountId: "account-a", draft },
      {
        version: 1,
        accountId: "account-a",
        draft: { ...draft, access_token: "secret" },
      },
      { version: 1, accountId: "account-a", draft, token: "secret" },
    ]) {
      storage().setItem(key, JSON.stringify(record));
      expect(readResearchDraft("account-a", storage)).toBeNull();
    }
    storage().setItem(key, "{invalid");
    expect(readResearchDraft("account-a", storage)).toBeNull();
    storage().setItem(key, "x".repeat(70_001));
    expect(readResearchDraft("account-a", storage)).toBeNull();
  });
  it("bounds fields while preserving unfinished invalid requirements", () => {
    const { storage } = memoryStorage();
    for (const invalid of [
      { ...draft, question: "x".repeat(1001) },
      { ...draft, requirementsText: "x".repeat(MAX_REQUIREMENTS_TEXT + 1) },
      { ...draft, depth: "Unlimited" },
      { ...draft, requireApproval: "yes" },
      { ...draft, token: "secret" },
    ])
      expect(writeResearchDraft("a", invalid as typeof draft, storage)).toBe(
        false,
      );
    const unfinished = { ...draft, requirementsText: "x".repeat(501) };
    expect(writeResearchDraft("a", unfinished, storage)).toBe(true);
    expect(readResearchDraft("a", storage)).toEqual(unfinished);
  });
  it("clears only the requested account", () => {
    const { storage } = memoryStorage();
    writeResearchDraft("a", draft, storage);
    writeResearchDraft("b", draft, storage);
    expect(clearResearchDraft("a", storage)).toBe(true);
    expect(readResearchDraft("a", storage)).toBeNull();
    expect(readResearchDraft("b", storage)).toEqual(draft);
  });
  it("handles denied storage access and quota/method failures", () => {
    const denied = () => {
      throw new Error("SecurityError");
    };
    const broken = () => ({
      getItem: denied,
      setItem: denied,
      removeItem: denied,
    });
    for (const storage of [denied, broken]) {
      expect(readResearchDraft("a", storage)).toBeNull();
      expect(writeResearchDraft("a", draft, storage)).toBe(false);
      expect(clearResearchDraft("a", storage)).toBe(false);
    }
  });
  it("extracts only a bounded public account id from the existing session shape", () => {
    expect(
      researchDraftAccount({
        user: { id: "a", email: "person@example.test" },
        token: "secret",
      }),
    ).toBe("a");
    for (const body of [
      null,
      {},
      { user: { email: "a" } },
      { user: { id: "" } },
      { user: { id: "x".repeat(129) } },
    ])
      expect(researchDraftAccount(body)).toBeNull();
  });
});
