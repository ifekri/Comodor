/**
 * The shell's keyboard names and the keys it must never take (FR-017;
 * contracts/workbench-shell.md, "Rules").
 */

import { describe, expect, test } from "bun:test";

import { commands } from "../src/commands.ts";
import {
  isEditable, isReserved, keyName, modifierName, platformOf, reachesShell, type KeyEventLike,
} from "../src/shell/keys.ts";

function key(name: string, mods: Partial<KeyEventLike> = {}): KeyEventLike {
  return { key: name, shiftKey: false, ctrlKey: false, altKey: false, metaKey: false, ...mods };
}

describe("the primary modifier", () => {
  test("is Command on macOS and Control elsewhere", () => {
    expect(platformOf("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)")).toBe("mac");
    expect(platformOf("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("other");
    expect(platformOf("Mozilla/5.0 (X11; Linux x86_64)")).toBe("other");
    expect(modifierName("mac")).toBe("Cmd");
    expect(modifierName("other")).toBe("Ctrl");
    expect(keyName(key("k", { metaKey: true }), "mac")).toBe("mod+k");
    expect(keyName(key("k", { ctrlKey: true }), "other")).toBe("mod+k");
    expect(keyName(key("k", { ctrlKey: true }), "mac")).toBeUndefined();
    expect(keyName(key("k", { metaKey: true }), "other")).toBeUndefined();
  });
});

describe("key names", () => {
  test("name the shell's bindings", () => {
    expect(keyName(key("K", { ctrlKey: true, shiftKey: false }), "other")).toBe("mod+k");
    expect(keyName(key("1", { ctrlKey: true }), "other")).toBe("mod+1");
    expect(keyName(key("3", { metaKey: true }), "mac")).toBe("mod+3");
    expect(keyName(key("/", { ctrlKey: true }), "other")).toBe("mod+/");
    expect(keyName(key("M", { ctrlKey: true, shiftKey: true }), "other")).toBe("mod+shift+m");
    expect(keyName(key("F6"), "other")).toBe("f6");
    expect(keyName(key("F6", { shiftKey: true }), "other")).toBe("shift+f6");
    expect(keyName(key("Escape"), "other")).toBe("escape");
    expect(keyName(key("Enter"), "other")).toBe("enter");
  });

  test("punctuation is named by the character, whether or not the layout needed Shift", () => {
    // `/` is Shift+7 on a German layout: the same binding.
    expect(keyName(key("/", { ctrlKey: true, shiftKey: true }), "other")).toBe("mod+/");
    expect(keyName(key("/", { metaKey: true, shiftKey: true }), "mac")).toBe("mod+/");
    // Letters and digits keep their Shift state.
    expect(keyName(key("m", { ctrlKey: true, shiftKey: true }), "other")).toBe("mod+shift+m");
    expect(keyName(key("m", { ctrlKey: true }), "other")).toBe("mod+m");
  });

  test("a lone modifier names nothing", () => {
    for (const lone of ["Control", "Shift", "Alt", "Meta"]) {
      expect(keyName(key(lone, { ctrlKey: lone === "Control", shiftKey: lone === "Shift" }), "other"))
        .toBeUndefined();
    }
  });
});

describe("reserved keys", () => {
  const reserved = [
    "tab", "shift+tab", "k", "a", "1", "/", " ", "arrowleft", "arrowright", "arrowup", "arrowdown",
    "home", "end", "pageup", "pagedown", "shift+arrowleft", "mod+arrowleft", "mod+shift+end", "mod+home",
    "mod+a", "mod+c", "mod+x", "mod+v", "mod+z", "mod+y", "mod+shift+z", "mod+w", "mod+q", "mod+m",
    "mod+h", "mod+.", "alt+f4", "mod+alt+arrowleft", "mod+alt+arrowright", "mod+r", "f5", "mod+=",
    "mod++", "mod+-", "mod+0",
  ];

  test("each key the platform or text editing needs is reserved", () => {
    for (const name of reserved) expect(isReserved(name)).toBe(true);
    for (const free of ["mod+k", "mod+1", "mod+/", "mod+shift+m", "f6", "shift+f6"]) {
      expect(isReserved(free)).toBe(false);
    }
  });

  test("no binding of the window's registry is reserved", () => {
    // Enter and Escape are D1's composer keys, handled by the composer itself.
    const bound = commands.allBindings().map((binding) => binding.key)
      .filter((name) => name !== "enter" && name !== "escape");
    for (const name of bound) expect([name, isReserved(name)]).toEqual([name, false]);
  });
});

describe("text fields", () => {
  test("only modified keys and F6 reach the shell from a text field", () => {
    expect(reachesShell("k", true)).toBe(false);
    expect(reachesShell("shift+k", true)).toBe(false);
    expect(reachesShell("enter", true)).toBe(false);
    expect(reachesShell("escape", true)).toBe(false);
    expect(reachesShell("mod+k", true)).toBe(true);
    expect(reachesShell("f6", true)).toBe(true);
    expect(reachesShell("shift+f6", true)).toBe(true);
    expect(reachesShell("k", false)).toBe(true);
  });

  test("an editable target is recognised", () => {
    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    const button = document.createElement("button");
    expect([isEditable(input), isEditable(textarea), isEditable(editable), isEditable(button)])
      .toEqual([true, true, true, false]);
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    expect(isEditable(checkbox)).toBe(false);
  });
});
