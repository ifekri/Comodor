import type { Metadata, Viewport } from 'next';
import { Instrument_Serif, Inter, JetBrains_Mono } from 'next/font/google';
import { ThemeToggle } from '@/components/ThemeToggle';
import { site } from '@/lib/site.config';
import '@/styles/globals.css';
import '@/styles/components.css';

/*
 * Three faces, each with one job.
 *
 * Instrument Serif carries the display type. A high-contrast serif on a
 * developer-tool page is the decision that stops it looking like the eleven
 * other developer-tool pages, and it is why the layout reads as typeset rather
 * than assembled — but it is display only, never body.
 *
 * Inter does the work: interface text, notes, labels.
 *
 * JetBrains Mono lives inside the terminal figures, where the code is.
 *
 * `display: swap` throughout, so nothing on this page waits on a font.
 */
const serif = Instrument_Serif({
  subsets: ['latin'],
  weight: '400',
  style: ['normal', 'italic'],
  variable: '--font-serif',
  display: 'swap',
});

const sans = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
});

const mono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  metadataBase: new URL(site.url),
  title: {
    default: `${site.name} — ${site.tagline}`,
    template: `%s — ${site.name}`,
  },
  description: site.description,
  applicationName: site.name,
  keywords: [
    'terminal agent', 'coding agent', 'CLI', 'AI pair programmer',
    'self-improving', 'developer tools', 'python', 'MCP',
  ],
  authors: [{ name: site.name, url: site.url }],
  openGraph: {
    type: 'website',
    url: site.url,
    siteName: site.name,
    title: `${site.name} — ${site.tagline}`,
    description: site.description,
  },
  twitter: {
    card: 'summary_large_image',
    title: `${site.name} — ${site.tagline}`,
    description: site.description,
  },
  alternates: { canonical: site.url },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: '#faf8f4',
  // Both, so form controls and scrollbars follow whichever theme is applied.
  colorScheme: 'light dark',
};

/*
 * Applied before the first paint, which is why it is a blocking inline script
 * and not a component. React runs after the browser has already painted; on a
 * page that is either near-white or near-black, that one frame of the wrong
 * theme is the most visible bug the feature could have.
 *
 * Deliberately tiny and deliberately wrapped in try/catch: localStorage throws
 * in some private modes, and a theme preference is not worth a blank page.
 */
const NO_FLASH = `
try {
  var stored = localStorage.getItem('comodor-theme');
  var dark = stored
    ? stored === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  var root = document.documentElement;
  root.dataset.theme = dark ? 'dark' : 'light';
  root.style.colorScheme = dark ? 'dark' : 'light';
} catch (e) {}
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${serif.variable} ${sans.variable} ${mono.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH }} />
        {/*
          The hero artwork is fetched by [Earth] rather than inlined, so that
          the page itself stays small on a host that only speaks gzip. Starting
          it here means it is in flight from the first byte of the document,
          instead of waiting for React to mount.
        */}
        <link
          rel="preload"
          as="fetch"
          type="image/svg+xml"
          href={`${process.env.NEXT_PUBLIC_BASE_PATH ?? ''}/earth.svg`}
          crossOrigin="anonymous"
        />
      </head>
      <body>
        <a className="skip-link" href="#install">
          Skip to the install command
        </a>
        <ThemeToggle />
        {children}
      </body>
    </html>
  );
}
