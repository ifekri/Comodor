import type { Metadata, Viewport } from 'next';
import { Instrument_Serif, Inter, JetBrains_Mono } from 'next/font/google';
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
  colorScheme: 'light',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${serif.variable} ${sans.variable} ${mono.variable}`}
    >
      <body>
        <a className="skip-link" href="#install">
          Skip to the install command
        </a>
        {children}
      </body>
    </html>
  );
}
