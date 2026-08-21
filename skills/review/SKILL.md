---
name: review
description: Review a change for correctness before it is committed
triggers: [review, diff, pull request, pr]
---

Read the whole change before saying anything about it. A review written from
the first hunk is a review of the first hunk.

Report only what would block a merge. A review that lists twenty nitpicks
buries the one thing that mattered, and the reader learns to skim the next one.

Look, in this order:

1. **Correctness.** Does it do what it says? Check the edges the author is
   least likely to have run: empty input, one item, the maximum, the error
   path.
2. **Silent failures.** An exception that is caught and dropped, a return value
   nobody checks, a write whose result is ignored.
3. **Tests that assert the implementation rather than the behaviour.** Those
   pass forever and catch nothing; they are worse than no test, because they
   look like coverage.
4. **Anything the change makes harder to change next time.**

For each finding, say what breaks and when. "This is fragile" is not a finding;
"a second call with the same id raises KeyError, and `sync()` calls it in a
loop" is.

If the change is fine, say so in one line and stop.
