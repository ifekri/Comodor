import { Fragment } from 'react';

/**
 * A skill file, rendered as the file itself rather than as prose about it.
 *
 * The source is one template literal, so what the page shows is what somebody
 * would actually type into `~/.comodor/skills/review.md` — copy it out and it
 * works. Highlighting is applied afterwards, per line, instead of being woven
 * through the markup, which keeps the content editable by anyone.
 */
const SOURCE = `---
name: review
description: Review a change for correctness
triggers: [review, diff, pull request, pr]
---

Read the whole change before saying anything about it.

Look for, in this order: correctness, then silent failures, then
tests that assert the implementation rather than the behaviour.

Report only what would block a merge. A review that lists twenty
nitpicks buries the one thing that mattered.`;

/** `key: value` inside the front matter, which is everything above the second `---`. */
const HEADER_FIELD = /^([a-z]+):(.*)$/;

function line(text: string, inHeader: boolean) {
  if (text === '---') {
    return <span className="skill-file__rule">---</span>;
  }

  const field = inHeader ? HEADER_FIELD.exec(text) : null;
  if (!field) {
    return text;
  }

  return (
    <>
      <span className="skill-file__key">{field[1]}</span>:{field[2]}
    </>
  );
}

export function SkillFile() {
  const lines = SOURCE.split('\n');
  const closingRule = lines.indexOf('---', 1);

  return (
    <pre className="skill-file__body">
      {lines.map((text, index) => (
        <Fragment key={index}>
          {line(text, index < closingRule)}
          {index < lines.length - 1 ? '\n' : null}
        </Fragment>
      ))}
    </pre>
  );
}
