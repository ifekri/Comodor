/**
 * The harness's reading of the bridge record (e2e/record.mjs): a last line
 * still being written is not an entry yet; every finished line must parse.
 */

import { describe, expect, test } from "bun:test";

import { recordLines as read } from "../e2e/record.mjs";

describe("the bridge record", () => {
  test("is read line by line", () => {
    expect(read('{"kind":"command"}\n{"kind":"inbound"}\n')).toEqual([{ kind: "command" }, { kind: "inbound" }]);
    expect(read("")).toEqual([]);
  });

  test("leaves out a last line still being written", () => {
    expect(read('{"kind":"command"}\n{"kind":"inbound","value":{"line":"{\\"ver')).toEqual([{ kind: "command" }]);
  });

  test("refuses a finished line that does not parse", () => {
    expect(() => read('{"kind":"command"}\n{"kind":\n{"kind":"inbound"}\n')).toThrow();
  });
});
