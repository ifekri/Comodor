import { readFileSync } from 'node:fs';
import path from 'node:path';

/**
 * The hero figure: the supplied artwork, unaltered.
 *
 * `assets/earth.svg` is byte-for-byte what was handed over — 468 paths and 698
 * SMIL animations — and nothing here edits it. It is read once at build time
 * and inlined into the page, which matters for two reasons: an `<img>` would
 * seal the drawing inside its own document where no stylesheet can reach it,
 * and inlining costs no second request.
 *
 * 474 KB of markup sounds alarming and is not. It is almost entirely repeated
 * coordinate data, and App Router puts the rendered server tree in the flight
 * payload as well as the HTML, so the page really does carry the drawing
 * twice — 1.0 MB of it. Measured on the wire, that whole page is **48 KB under
 * Brotli**, because the second copy is a back-reference to the first and costs
 * almost nothing; 164 KB gzipped is the floor for a client too old to ask for
 * better. Both hosts serve Brotli.
 *
 * The recolouring is done entirely in the stylesheet, by matching the two
 * greens the file already carries — see `.earth` in components.css. A CSS rule
 * outranks a presentation attribute, so `stroke="#129355"` becomes the site's
 * ink without a single character of the artwork being rewritten, and the
 * colours can still differ between the light and dark themes. Editing the file
 * would have baked one palette in and left the other impossible.
 *
 * Read with `readFileSync` deliberately: this is a server component and the
 * page is statically generated, so it runs once during the build and never at
 * request time.
 */

const artwork = readFileSync(
  path.join(process.cwd(), 'assets', 'earth.svg'),
  'utf8',
);

export function Earth() {
  return (
    <div
      className="earth"
      role="img"
      aria-label="A globe drawn as a network of connected points"
      dangerouslySetInnerHTML={{ __html: artwork }}
    />
  );
}
