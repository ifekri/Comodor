/**
 * The macOS reduced-motion transition's restoration (D2 follow-up): the
 * original setting is put back exactly — its type, its value, or its
 * absence — and only a read-back that matches it in every part counts.
 */

import { describe, expect, test } from "bun:test";

import { macRestoreArguments, macRestoredExactly, macTypeFlag } from "../e2e/os-preferences.mjs";

describe("the type of the original setting", () => {
  test("is read from `defaults read-type`", () => {
    expect(macTypeFlag("Type is boolean\n")).toBe("-bool");
    expect(macTypeFlag("Type is integer")).toBe("-int");
    expect(macTypeFlag("Type is float")).toBe("-float");
    expect(macTypeFlag("Type is string")).toBe("-string");
  });

  test("is unknown for anything else, so nothing is changed", () => {
    expect(macTypeFlag("Type is dictionary")).toBeNull();
    expect(macTypeFlag("")).toBeNull();
    expect(macTypeFlag(undefined)).toBeNull();
  });
});

describe("restoring the original", () => {
  test("deletes a key that was absent", () => {
    expect(macRestoreArguments({ absent: true })).toEqual(["delete", "com.apple.universalaccess", "reduceMotion"]);
  });

  test("writes a boolean back as the boolean it was", () => {
    expect(macRestoreArguments({ absent: false, flag: "-bool", value: "1" }))
      .toEqual(["write", "com.apple.universalaccess", "reduceMotion", "-bool", "true"]);
    expect(macRestoreArguments({ absent: false, flag: "-bool", value: "0" }))
      .toEqual(["write", "com.apple.universalaccess", "reduceMotion", "-bool", "false"]);
  });

  test("writes any other type back with its own type and value", () => {
    expect(macRestoreArguments({ absent: false, flag: "-int", value: "1" }))
      .toEqual(["write", "com.apple.universalaccess", "reduceMotion", "-int", "1"]);
  });
});

describe("a restoration counts", () => {
  const present = { absent: false, flag: "-bool", value: "1", effective: true };
  const missing = { absent: true, effective: false };

  test("only when the key, its type, its value and the effective value all match", () => {
    expect(macRestoredExactly(present, { ...present })).toBe(true);
    expect(macRestoredExactly(present, { ...present, value: "0" })).toBe(false);
    expect(macRestoredExactly(present, { ...present, flag: "-int" })).toBe(false);
    expect(macRestoredExactly(present, { ...present, effective: false })).toBe(false);
    expect(macRestoredExactly(present, { absent: true, effective: true })).toBe(false);
  });

  test("for an absent key, only when it is absent again with the original effective value", () => {
    expect(macRestoredExactly(missing, { absent: true, effective: false })).toBe(true);
    expect(macRestoredExactly(missing, { absent: false, flag: "-bool", value: "0", effective: false })).toBe(false);
    expect(macRestoredExactly(missing, { absent: true, effective: true })).toBe(false);
  });
});
