/**
 * How a view inside the shell runs a command: by id, through the one
 * registry, with the shell's context. Absent outside a shell.
 */

import { createContext } from "react";

export const ShellRun = createContext<((id: string) => void) | null>(null);
