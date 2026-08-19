import { CopyButton } from '@/components/CopyButton';
import { Figures } from '@/components/Figures';
import { Hero } from '@/components/Hero';
import { InstallCommand } from '@/components/InstallCommand';
import { ReflexScroll } from '@/components/ReflexScroll';
import { Section } from '@/components/Section';
import { SkillFile } from '@/components/SkillFile';
import { alternatives, site } from '@/lib/site.config';

export default function Home() {
  return (
    <main>
      <Hero />

      {/* -- 01 ------------------------------------------------------------ */}
      <Section id="reflex" number="01">
        <div className="grid split">
          <div className="split__text">
            <p className="eyebrow">Reflex</p>
            <h2>Most agents remember what you tell&nbsp;them.</h2>
          </div>
          <div className="split__aside">
            <p className="lede">
              Comodor learns from what you fix. Correction is the signal nobody
              else collects — frequent, precise, and free, because you produce
              it just by working. Scroll through it.
            </p>
          </div>
        </div>
      </Section>

      <ReflexScroll />

      {/* -- 02 ------------------------------------------------------------ */}
      <Section id="signals" number="02">
        <div className="grid split">
          <div className="split__text">
            <h2>Five signals, none of which cost anything.</h2>
          </div>
          <div className="split__aside">
            <p className="lede">
              All of them are produced by ordinary use. None require a model
              call, and none take longer than a millisecond to read.
            </p>
          </div>
        </div>

        <dl className="signals">
          {[
            ['You rewrite a file it wrote', 'The diff is the preference — quotes, indentation, annotations, verbosity.'],
            ['You press /undo', 'An outright rejection of what it produced.'],
            ['You deny a command', 'One thing this user does not want run.'],
            ['You ask the same thing twice', 'The answer missed.'],
            ['A tool fails the same way twice', 'A verified pitfall in this environment.'],
          ].map(([signal, meaning]) => (
            <div className="signal" key={signal} data-reveal>
              <dt>{signal}</dt>
              <dd>{meaning}</dd>
            </div>
          ))}
        </dl>

        <p className="lede pullquote" data-reveal>
          Each becomes a rule carrying its evidence — not{' '}
          <em>&ldquo;I think you prefer single quotes&rdquo;</em> but{' '}
          <code>31 of 34 literals</code>. How much evidence a rule needs depends
          on where it came from: four agreeing observations to trust your
          codebase, two for an edit you made, one for something you said
          outright.
        </p>
      </Section>

      {/* -- 03 ------------------------------------------------------------ */}
      <Section id="skills" number="03">
        <div className="grid split">
          <div className="split__text">
            <p className="eyebrow">Skills</p>
            <h2>And what you would rather write down yourself.</h2>
          </div>
          <div className="split__aside">
            <p className="lede">
              A Markdown file describing how <em>you</em> want a kind of work
              done. Comodor loads one only when the request calls for it, so
              twenty skills cost no more per turn than one.
            </p>
          </div>
        </div>

        <div className="skill-layout">
          <figure className="skill-file" data-reveal>
            <SkillFile />
            <figcaption>~/.comodor/skills/review.md</figcaption>
          </figure>

          <div className="notes">
            {[
              ['An open format', 'A single file, or a folder with SKILL.md and its references — the agentskills.io standard, so a skill written for another agent runs here unchanged.'],
              ['Loaded on demand', 'Bundled files are named in the prompt and never inlined. A skill can carry a thousand-line reference and cost nothing until the turn that needs it.'],
              ['Two folders', 'Yours, and the project’s — committed with the repository, and it wins on a name clash.'],
              ['Drafted for you', 'When a procedure has worked three times, Comodor offers it back as a finished file. Nothing is written until you say so.'],
            ].map(([title, body]) => (
              <div className="note" key={title} data-reveal>
                <h3>{title}</h3>
                <p>{body}</p>
              </div>
            ))}
          </div>
        </div>
      </Section>

      {/* -- 04 ------------------------------------------------------------ */}
      <Section id="speed" number="04">
        <div className="grid split">
          <div className="split__text">
            <p className="eyebrow">Speed</p>
            <h2>Memory that costs nothing on the turn.</h2>
          </div>
          <div className="split__aside">
            <p className="lede">
              Recall sits between pressing Enter and the first token, so it is
              measured rather than assumed — and enforced as a ceiling by the
              test suite.
            </p>
          </div>
        </div>

        <Figures />

        <p className="lede pullquote" data-reveal>
          A RAM mirror holds every lesson with its tokens pre-computed, so a
          lookup touches only the documents sharing a word with the query — and
          the candidate set is capped, which is why the cost stops growing with
          the corpus. A background writer batches commits, so nothing
          user-facing waits on the disk. And the ranking runs while you are
          still typing.
        </p>
      </Section>

      {/* -- 05 ------------------------------------------------------------ */}
      <Section id="control" number="05">
        <div className="grid split">
          <div className="split__text">
            <p className="eyebrow">Control</p>
            <h2>An agent you can leave running.</h2>
          </div>
          <div className="split__aside">
            <p className="lede">
              Reads never prompt. Writes show a diff. Commands and network calls
              always ask. <code>--yes</code> exists for CI and is a default
              nowhere.
            </p>
          </div>
        </div>

        <div className="cards">
          {[
            ['Checkpoints', 'Files are snapshotted before any change, and /undo restores them.'],
            ['A deny list', 'No prompt can talk past it, for the commands that are never acceptable.'],
            ['Workspace confinement', 'Writes outside the project are refused by default.'],
            ['Redaction', 'Keys and tokens are stripped from logs, transcripts and exports.'],
          ].map(([title, body]) => (
            <div className="card" key={title} data-reveal>
              <h3>{title}</h3>
              <p>{body}</p>
            </div>
          ))}
        </div>

        <div className="doctor" data-reveal>
          <div className="doctor__text">
            <h3>When something is wrong, it repairs itself</h3>
            <p>
              <code>comodor doctor</code> checks nine things and states a fix
              for each one it can. <code>--fix</code> applies them and
              re-checks. It repairs only what it can rebuild — a corrupt search
              index is a cache, so it goes; a corrupt config holds your API key,
              so it is reported and left exactly as it was.
            </p>
          </div>

          <div className="term term--wide">
            <div className="term__body term__body--tight">
              <p className="term__row">
                <span className="doctor__ok">ok</span>
                <span className="doctor__name">provider</span>
                <span className="term__dim">Anthropic · claude-sonnet-4-5</span>
              </p>
              <p className="term__row">
                <span className="doctor__warn">warn</span>
                <span className="doctor__name">session search</span>
                <span className="term__dim">the index is corrupt</span>
              </p>
              <p className="term__row term__row--indent">
                <span className="term__dim">
                  → delete it — it is a cache built from the transcripts
                </span>
              </p>
              <p className="term__row">
                <span className="doctor__ok">ok</span>
                <span className="doctor__name">mcp servers</span>
                <span className="term__dim">2 enabled and reachable</span>
              </p>
              <p className="term__row term__row--gap">
                <span className="term__dim">
                  1 of these can be repaired automatically:{' '}
                </span>
                <span className="term__amber">comodor doctor --fix</span>
              </p>
            </div>
          </div>
        </div>
      </Section>

      {/* -- 06 ------------------------------------------------------------ */}
      <Section id="mcp" number="06">
        <div className="grid split">
          <div className="split__text">
            <p className="eyebrow">MCP</p>
            <h2>Tools that live in other programs.</h2>
          </div>
          <div className="split__aside">
            <p className="lede">
              Twelve Model Context Protocol servers ship in a catalogue with
              their commands and what each can reach. Anything else in the
              ecosystem takes one line.
            </p>
          </div>
        </div>

        <ul className="servers">
          {[
            'Filesystem', 'Git', 'GitHub', 'Fetch', 'Memory',
            'Sequential thinking', 'SQLite', 'PostgreSQL', 'Puppeteer',
            'Brave Search', 'Slack', 'Time',
          ].map((name) => (
            <li key={name} data-reveal>
              {name}
            </li>
          ))}
        </ul>

        <div className="snippet" data-reveal>
          <code>comodor mcp add filesystem --path ~/work</code>
          <CopyButton
            value="comodor mcp add filesystem --path ~/work"
            label="copy"
          />
        </div>

        <p className="lede pullquote" data-reveal>
          Nothing starts until it is used, so a server you never touch costs
          nothing. What each one can reach is stated before you enable it —
          &ldquo;only the directory you name&rdquo; and &ldquo;everything your
          token can reach&rdquo; are different kinds of permission, and the
          difference belongs in front of the person deciding.
        </p>
      </Section>

      {/* -- 07 ------------------------------------------------------------ */}
      <Section id="install" number="07" className="closing">
        <div className="grid split">
          <div className="split__text">
            <p className="eyebrow">Install</p>
            <h2>One line, and it finishes the job.</h2>
          </div>
          <div className="split__aside">
            <p className="lede">
              It uses <code>uv</code> or <code>pipx</code> if you have them,
              builds an isolated environment if you have a working Python, and
              fetches what it needs if you have neither — then runs{' '}
              <code>{site.command}</code> once to prove it worked.
            </p>
          </div>
        </div>

        <div className="closing__install" data-reveal>
          <InstallCommand />
        </div>

        <div className="alts">
          {alternatives.map((alternative) => (
            <div className="alt" key={alternative.label} data-reveal>
              <span className="alt__label">{alternative.label}</span>
              <code className="alt__command">{alternative.command}</code>
              <CopyButton value={alternative.command} label="copy" />
            </div>
          ))}
        </div>

        <p className="verify" data-reveal>
          Prefer to read before you run? <a href="/install.sh">install.sh</a>{' '}
          and <a href="/install.ps1">install.ps1</a> are served as plain text.
          Everything Comodor does after that is on{' '}
          <a href={site.repo}>GitHub</a>.
        </p>
      </Section>

      <footer className="footer">
        <div className="wrap footer__inner">
          <div className="footer__mark">
            <strong>{site.name}</strong>
            <span>{site.tagline}</span>
          </div>
          <nav className="footer__links" aria-label="Elsewhere">
            <a href={site.repo}>GitHub</a>
            <a href={site.pypiUrl}>PyPI</a>
            <a href="#top">Top</a>
          </nav>
        </div>
      </footer>
    </main>
  );
}
