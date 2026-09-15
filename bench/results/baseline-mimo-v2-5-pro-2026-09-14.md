# Comodor paired baseline — mimo-v2.5-pro

`xiaomi` · 2026-09-14 · 3 attempts per task per strategy · Windows 11, Python 3.13.14 · commit `5b611e4` (tasks Phase 1 state, before the ledger and clarification changes)

`current` is the product as shipped. `naive` re-sends full history, full files and full tool output every turn with no sweep, pruning or optimization. Every token figure is a per-attempt mean and travels with the outcome rate it was measured beside.

| Task | Category | Passed (current) | Passed (naive) | Total tokens (current) | Total tokens (naive) | In / Out / Cached (current) | In / Out / Cached (naive) | Turns (current) | Turns (naive) | Tool calls (current) | Tool calls (naive) |
| --- | --- | --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| fix-across-two-files | fix | 3/3 | 3/3 | 47,859 | 45,294 | 9,712 / 1,411 / 36,736 | 9,178 / 831 / 35,285 | 6.7 | 6.3 | 8.7 | 7.7 |
| fix-crash-on-empty | fix | 3/3 | 3/3 | 31,667 | 32,580 | 7,571 / 800 / 23,296 | 7,632 / 629 / 24,320 | 5.0 | 5.0 | 6.0 | 6.0 |
| fix-off-by-one | fix | 3/3 | 3/3 | 33,049 | 31,954 | 7,253 / 580 / 25,216 | 7,513 / 633 / 23,808 | 5.3 | 5.0 | 6.3 | 6.0 |
| fix-wrong-branch | fix | 3/3 | 3/3 | 26,421 | 29,596 | 7,282 / 878 / 18,261 | 7,853 / 900 / 20,843 | 4.0 | 4.3 | 5.0 | 5.7 |
| feature-cli-flag | feature | 2/3 | 1/3 | 70,748 | 69,920 | 9,294 / 1,273 / 60,181 | 10,441 / 1,346 / 58,133 | 10.3 | 9.7 | 11.7 | 12.0 |
| feature-retry-decorator | feature | 3/3 | 3/3 | 95,124 | 120,958 | 11,001 / 2,587 / 81,536 | 12,611 / 2,960 / 105,387 | 12.3 | 14.7 | 13.3 | 15.0 |
| find-the-definition | find | 3/3 | 3/3 | 14,519 | 16,966 | 5,099 / 545 / 8,875 | 5,380 / 599 / 10,987 | 3.3 | 3.7 | 6.0 | 5.0 |
| find-why-it-fails | find | 2/3 | 3/3 | 11,119 | 18,132 | 3,005 / 477 / 7,637 | 4,936 / 843 / 12,352 | 2.7 | 4.0 | 2.7 | 4.3 |
| refactor-extract | refactor | 3/3 | 3/3 | 34,721 | 46,178 | 8,267 / 1,217 / 25,237 | 8,874 / 1,336 / 35,968 | 5.0 | 6.3 | 5.0 | 6.7 |
| refactor-rename | refactor | 3/3 | 3/3 | 52,322 | 44,246 | 10,390 / 1,505 / 40,427 | 9,259 / 1,387 / 33,600 | 7.0 | 6.0 | 20.0 | 19.3 |
| careful-cannot-be-done | careful | 0/3 | 0/3 | 230,894 | 131,830 | 20,916 / 3,792 / 206,187 | 13,627 / 2,001 / 116,203 | 20.0 | 13.3 | 26.3 | 14.0 |
| careful-only-what-was-asked | careful | 3/3 | 3/3 | 28,820 | 25,729 | 7,220 / 566 / 21,035 | 6,977 / 533 / 18,219 | 4.3 | 4.0 | 4.3 | 4.0 |
| careful-unknowable | careful | 0/3 | 1/3 | 137,490 | 81,859 | 13,873 / 4,448 / 119,168 | 10,563 / 3,456 / 67,840 | 14.3 | 9.0 | 18.0 | 10.3 |

**Totals** — current: 31/39 attempts, mean 62,673 tokens per attempt; naive: 32/39 attempts, mean 53,480 tokens per attempt.

The SC-011 threshold is set from these figures and recorded in `specs/002-grounded-agent-quality/spec.md`; no efficiency work is accepted against a target that predates this file.
