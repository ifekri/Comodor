import { PLAIN_TEXT, readScript } from '@/lib/scripts';

/** The PowerShell installer, readable in a browser on any host. */
export const dynamic = 'force-static';

export async function GET() {
  return new Response(await readScript('install.ps1'), { headers: PLAIN_TEXT });
}
