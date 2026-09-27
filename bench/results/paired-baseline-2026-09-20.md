# Comodor paired baseline — benchmark-model

`benchmark-provider` · 2026-09-20 · 3 attempts per task per strategy · Windows 11, Python 3.13.14 · commit `be9cf6f`

`current` is the product as shipped. `naive` re-sends full history, full files and full tool output every turn with no sweep, pruning or optimization. Every token figure is a per-attempt mean and travels with the outcome rate it was measured beside.

| Task | Category | Passed (current) | Passed (naive) | Total tokens (current) | Total tokens (naive) | In / Out / Cached (current) | In / Out / Cached (naive) | Turns (current) | Turns (naive) | Tool calls (current) | Tool calls (naive) | Regression |
| --- | --- | --- | --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| fix-across-two-files | fix | 3/3 | 3/3 | 45,511 | 53,276 | 8,598 / 1,031 / 35,883 | 9,696 / 1,169 / 42,411 | 6.3 | 7.0 | 8.0 | 8.3 |  |
| fix-crash-on-empty | fix | 3/3 | 3/3 | 32,533 | 37,427 | 7,569 / 686 / 24,277 | 7,487 / 798 / 29,141 | 5.0 | 5.7 | 6.3 | 6.7 |  |
| fix-off-by-one | fix | 3/3 | 3/3 | 31,502 | 34,552 | 7,018 / 526 / 23,957 | 7,475 / 646 / 26,432 | 5.0 | 5.3 | 6.0 | 6.3 |  |
| fix-wrong-branch | fix | 3/3 | 3/3 | 31,891 | 26,873 | 7,678 / 746 / 23,467 | 7,603 / 689 / 18,581 | 4.7 | 4.0 | 6.0 | 5.0 |  |
| feature-cli-flag | feature | 2/3 | 2/3 | 72,767 | 102,554 | 9,214 / 1,409 / 62,144 | 11,203 / 1,985 / 89,365 | 10.0 | 13.3 | 11.3 | 13.0 |  |
| feature-retry-decorator | feature | 1/3 | 3/3 | 82,028 | 93,015 | 10,092 / 2,219 / 69,717 | 11,452 / 1,905 / 79,659 | 10.7 | 11.7 | 10.7 | 11.7 | **yes** |
| find-the-definition | find | 3/3 | 3/3 | 21,757 | 13,780 | 5,420 / 742 / 15,595 | 5,009 / 643 / 8,128 | 4.3 | 3.0 | 5.3 | 4.7 |  |
| find-why-it-fails | find | 3/3 | 1/3 | 16,798 | 16,688 | 5,108 / 981 / 10,709 | 4,855 / 1,102 / 10,731 | 3.7 | 3.7 | 4.3 | 4.0 |  |
| refactor-extract | refactor | 3/3 | 3/3 | 40,960 | 38,384 | 8,734 / 1,250 / 30,976 | 8,265 / 1,254 / 28,864 | 5.7 | 5.3 | 5.7 | 5.7 |  |
| refactor-rename | refactor | 3/3 | 3/3 | 36,135 | 41,059 | 8,912 / 1,239 / 25,984 | 8,957 / 1,190 / 30,912 | 5.0 | 5.7 | 18.0 | 18.3 |  |
| careful-cannot-be-done | careful | 0/3 | 0/3 | 171,982 | 157,417 | 18,558 / 5,371 / 148,053 | 15,135 / 4,107 / 138,176 | 13.0 | 14.0 | 15.0 | 15.7 |  |
| careful-only-what-was-asked | careful | 3/3 | 3/3 | 25,388 | 25,536 | 7,082 / 450 / 17,856 | 7,147 / 448 / 17,941 | 4.0 | 4.0 | 4.0 | 4.0 |  |
| careful-unknowable | careful | 0/3 | 3/3 | 111,465 | 19,184 | 12,059 / 3,428 / 95,979 | 6,622 / 1,171 / 11,392 | 13.0 | 3.0 | 15.7 | 7.0 | **yes** |

**Totals** — current: 30/39 attempts, mean 55,440 tokens per attempt; naive: 33/39 attempts, mean 50,750 tokens per attempt.

Token accounting version 2. A total from one accounting version is not directly comparable with a total from another: version 2 adds `written_tokens` and every auxiliary provider call, including the compaction summary.

The SC-011 threshold is set from these figures and recorded in `specs/002-grounded-agent-quality/spec.md`; no efficiency work is accepted against a target that predates this file.
