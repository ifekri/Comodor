import { Earth } from './Earth';
import { HeroEntrance } from './HeroEntrance';
import { InstallCommand } from './InstallCommand';

/**
 * The opening.
 *
 * One idea, held for the whole viewport: the claim, the command that acts on
 * it, and the figure. The sentence and the install line sit together in the
 * left column, because the visitor who has already decided should not have to
 * go looking; the figure holds the right.
 *
 * Nothing here is interactive, so nothing here is a client component. The
 * entrance lives in [HeroEntrance], a sibling that renders null, which is what
 * keeps the inlined artwork from being serialised a second time.
 */
export function Hero() {
  return (
    <header className="hero" id="top">
      <HeroEntrance />
      <div className="wrap">
        <div className="hero__rule" aria-hidden="true" />

        <div className="hero__grid">
          <div className="hero__text">
            <h1 className="hero__title">
              <span className="hero__line">
                <span>It learns the way</span>
              </span>
              <span className="hero__line">
                <span>
                  you <em>correct</em> it.
                </span>
              </span>
            </h1>

            <p className="lede hero__lede">
              A terminal coding agent that reads the edits you make to its
              output and turns them into rules — no second model call, no
              waiting, nothing to configure. Fix something once and the next
              answer already obeys.
            </p>

            <div className="hero__install">
              <InstallCommand />
            </div>

            <dl className="hero__meta">
              <div>
                <dt>Providers</dt>
                <dd>
                  <span className="tabular">18</span>, or your own
                </dd>
              </div>
              <div>
                <dt>Recall</dt>
                <dd>
                  <span className="tabular">0.38 ms</span>, flat
                </dd>
              </div>
              <div>
                <dt>Runs</dt>
                <dd>anywhere with a terminal</dd>
              </div>
            </dl>
          </div>

          <figure className="hero__figure">
            <Earth />
            <figcaption className="hero__caption">
              Eighteen providers, your own endpoint, or a model on your own
              machine.
            </figcaption>
          </figure>
        </div>

      </div>
    </header>
  );
}
