<?php
/**
 * get.comodor.ai — one address, the right installer.
 *
 *     curl -fsSL get.comodor.ai | sh      macOS, Linux, BSD
 *     irm get.comodor.ai | iex            Windows
 *
 * The site itself is a static export on GitHub Pages, which cannot look at a
 * request and so cannot answer two different clients differently. This is the
 * three lines of hosting that can: it reads who is asking and sends them on.
 *
 * A redirect rather than a proxy. There is then one copy of each script, at
 * the address the site already serves it from, and this file never has to be
 * redeployed when an installer changes. Verified that both clients follow a
 * cross-host 302 and receive the body intact — `curl -fsSL` because `-L` is
 * in there, and `Invoke-RestMethod` because it follows by default.
 *
 * Nothing here touches comodor.ai. It is a separate subdomain with a separate
 * document root, and if it were deleted tomorrow every existing install
 * command would keep working.
 */

declare(strict_types=1);

const SITE = 'https://comodor.ai';
const SHELL_SCRIPT = SITE . '/install.sh';
const POWERSHELL_SCRIPT = SITE . '/install.ps1';

/**
 * Windows PowerShell and PowerShell 7 both name themselves in the agent:
 *
 *   Mozilla/5.0 (Windows NT 10.0; …) WindowsPowerShell/5.1.19041.1
 *   Mozilla/5.0 (Windows NT 10.0; …) PowerShell/7.4.0
 *
 * Checked before the browser test, because both of those begin "Mozilla/5.0"
 * and would otherwise be mistaken for somebody reading the page.
 */
const POWERSHELL_SIGNS = ['powershell', 'pwsh'];

/** Anything that pipes. An empty agent is one of these far more often than a browser. */
const FETCHER_SIGNS = ['curl', 'wget', 'httpie', 'fetch', 'aria2', 'lwp-request', 'python-requests'];

$agent = strtolower($_SERVER['HTTP_USER_AGENT'] ?? '');
$asked = strtolower($_SERVER['QUERY_STRING'] ?? '');

// Explicit beats guessed. `get.comodor.ai?ps1` for anybody whose client lies
// about itself, and for a link that has to be unambiguous.
if ($asked === 'ps1' || $asked === 'windows') {
    send(POWERSHELL_SCRIPT);
}
if ($asked === 'sh' || $asked === 'unix') {
    send(SHELL_SCRIPT);
}

if (matches($agent, POWERSHELL_SIGNS)) {
    send(POWERSHELL_SCRIPT);
}
if ($agent === '' || matches($agent, FETCHER_SIGNS)) {
    send(SHELL_SCRIPT);
}

// A person, in a browser. Send them to the page, which detects their system
// and shows the line to copy — a wall of shell script is not an answer to
// somebody who typed this into an address bar.
send(SITE . '/#install');


function matches(string $agent, array $signs): bool
{
    foreach ($signs as $sign) {
        if (str_contains($agent, $sign)) {
            return true;
        }
    }
    return false;
}

function send(string $where): never
{
    // 302, never 301: a permanent redirect would be cached by the client and
    // by everything between, and this address deliberately answers differently
    // for different callers. `Vary` says the same thing to any cache that is
    // paying attention, which is the part that stops a shared proxy handing a
    // PowerShell script to somebody running sh.
    header('Vary: User-Agent');
    header('Cache-Control: no-store, max-age=0');
    header('Location: ' . $where, true, 302);

    // A body, for the client that ignores the redirect. It is a shell comment
    // and a PowerShell comment at once, so whichever of them is reading gets
    // something harmless and a sentence it can act on.
    header('Content-Type: text/plain; charset=utf-8');
    echo "# Comodor installer\n";
    echo "# This address redirects; your client did not follow it.\n";
    echo "#\n";
    echo "#   curl -fsSL " . SHELL_SCRIPT . " | sh\n";
    echo "#   irm " . POWERSHELL_SCRIPT . " | iex\n";
    exit;
}
