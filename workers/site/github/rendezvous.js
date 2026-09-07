/**
 * Where a finished connection waits for the terminal that asked for it.
 *
 * The browser and the terminal are two processes on two machines with nothing
 * between them. Until now the person was the channel: the callback page showed
 * a signed receipt and they copied it across. That works, needs no storage,
 * and is a chore in the middle of an otherwise automatic flow.
 *
 * This is the storage that removes the chore. One Durable Object per flow,
 * holding one small result for a few minutes.
 *
 * **Why a Durable Object and not something cheaper.** The requirement is
 * narrow and unforgiving: the browser writes once, the terminal reads
 * within seconds, and the read must never return a stale "pending" after the
 * write has happened. That is strong consistency on a single key.
 *
 * * **KV** is eventually consistent. A poll landing in a different colo can
 *   miss a write for up to a minute, which is exactly the window the terminal
 *   is polling in — the flow would appear to hang and then complete, or hang
 *   until it expired.
 * * **The Cache API** is per-colo by design. The browser and the terminal are
 *   routinely on different continents; the write would simply not be visible.
 * * **A module-scoped `Map`** lives in one isolate. Two requests are not
 *   promised the same isolate, and isolates are evicted between them.
 * * **D1** would work and is a database — a schema, a migration and a table of
 *   ten-minute rows for one integration, which is more infrastructure than the
 *   problem justifies.
 *
 * A Durable Object is a single-threaded actor addressed by name: `idFromName`
 * on the flow's nonce sends every request for that flow to the same instance,
 * wherever it is. Writes are ordered, reads see them, and the object stops
 * existing when its storage empties.
 *
 * **It is not a database of installations.** Nothing here outlives its alarm.
 * The authoritative record of a connection stays where it always was — the
 * config file and the private key on the machine that connected. What lives
 * here is one in-flight handshake, for as long as the handshake takes.
 */

import { LAUNCH_LIVES_FOR, RESULT_LIVES_FOR } from './config.js';
import { sameBytes } from './browser.js';

const KEY = 'result';
const SEEN = 'seen:';

/**
 * How many spent request nonces one flow remembers.
 *
 * A poll every two seconds across a fifteen-minute state is at most four
 * hundred and fifty, and the object is deleted when the flow ends — so this
 * is a ceiling against a caller that polls far faster than the agent does,
 * not a working limit. Reaching it refuses the poll rather than forgetting an
 * old nonce, because forgetting one is what re-opens the replay.
 */
const MOST_NONCES = 512;

/**
 * One connection flow.
 *
 * Addressed by the flow's nonce, which is inside the signed state and cannot
 * be edited. Knowing a nonce is enough to *address* this object and not enough
 * to read from it: `deliver` and `take` are called by the Worker, which checks
 * a signature from the flow's client key before it asks. See `proof.js`.
 */
export class ConnectionFlow {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    const url = new URL(request.url);
    const action = url.pathname.replace(/^\//, '');

    if (action === 'deliver') {
      const body = await request.json();
      // First writer wins. A second callback for one flow — a refresh, a
      // back button, a link opened twice — must not overwrite a result the
      // terminal may already be reading, and must not turn a completed
      // connection into a cancelled one.
      const existing = await this.state.storage.get(KEY);
      if (existing) {
        return Response.json({ stored: false, status: existing.status });
      }
      await this.state.storage.put(KEY, body);
      // The object deletes itself. Nothing here is meant to outlive the flow,
      // and an alarm is the only thing that runs without a request to carry
      // it.
      await this.state.storage.setAlarm(Date.now() + RESULT_LIVES_FOR * 1000);
      return Response.json({ stored: true, status: body.status });
    }

    if (action === 'take') {
      // A signature is checked before this is reached, and a valid signature
      // stays valid for as long as its timestamp is fresh — so a captured
      // poll can be sent again inside that window. The one-time result is not
      // the answer to that: it makes the flow have one winner without making
      // the winner be whoever sent the original request. A replay arriving
      // first would take the result and delete it, and the agent that started
      // the flow would poll a flow that no longer has anything in it.
      //
      // So the request nonce is spent here, in the one place that is
      // single-threaded per flow. Second use is refused, and refused before
      // the result is read.
      const { nonce } = await request.json();
      const spent = `${SEEN}${nonce}`;
      if (await this.state.storage.get(spent)) {
        return Response.json({ error: 'that request has already been used' },
          { status: 401 });
      }
      const seen = await this.state.storage.list({ prefix: SEEN, limit: MOST_NONCES });
      if (seen.size >= MOST_NONCES) {
        return Response.json({ error: 'too many requests for this flow' },
          { status: 429 });
      }
      await this.state.storage.put(spent, 1);

      const found = await this.state.storage.get(KEY);
      if (!found) return Response.json({ status: 'pending' });
      // Read once and gone. The terminal saves what it collects, and leaving
      // a copy behind would keep a grant readable by a second caller that
      // manages to sign correctly — which the key holder can, but only they,
      // and only until they have what they asked for.
      await this.state.storage.delete(KEY);
      return Response.json(found);
    }

    if (action === 'arm') {
      // The browser capability for this flow, stored as its hash. Written at
      // `install`, before the terminal has opened anything, so there is no
      // window in which a flow exists and cannot be started.
      const { digest, expires, state } = await request.json();
      // The state is kept here so the browser never has to carry it to the
      // launch page. It is not a secret — GitHub echoes it back in a query
      // string — but a value nobody has to hold is a value nobody can leak.
      await this.state.storage.put('launch', { digest, expires, state });
      await this.state.storage.setAlarm(Date.now() + RESULT_LIVES_FOR * 1000);
      return Response.json({ armed: true });
    }

    if (action === 'spend') {
      // One browser, once. The capability is compared against its stored
      // hash and then deleted, so a launch link that has been followed is a
      // link that no longer works — a refresh, a second tab, or somebody who
      // read it over a shoulder all arrive at the same closed door.
      const { digest } = await request.json();
      const armed = await this.state.storage.get('launch');
      if (!armed) return Response.json({ spent: false, why: 'gone' });
      if (armed.expires * 1000 <= Date.now()) {
        await this.state.storage.delete('launch');
        return Response.json({ spent: false, why: 'expired' });
      }
      if (!sameBytes(armed.digest, digest)) {
        // Deliberately not deleted. A wrong guess must not be able to burn
        // somebody else's capability before they use it.
        return Response.json({ spent: false, why: 'wrong' });
      }
      await this.state.storage.delete('launch');
      return Response.json({ spent: true, state: armed.state || '' });
    }

    if (action === 'claim-setup') {
      // The browser leg, taken once.
      //
      // A state is not a secret — it is in an address bar, a history and a
      // referrer — and the browser proves nothing else about itself. So
      // somebody holding a victim's state can walk it through `setup` with an
      // installation of their own, authorise as themselves, and have the
      // result delivered to the victim's terminal, which would connect to an
      // installation nobody there chose.
      //
      // This does not make the state secret; nothing can. What it does is
      // stop the flow being walked twice: whoever reaches `setup` first owns
      // the browser leg, and the second attempt is refused rather than
      // silently replacing the first. In the ordinary case the first is the
      // browser the terminal just opened, seconds earlier, which narrows the
      // opportunity from the state's whole lifetime to that gap.
      const already = await this.state.storage.get('setup');
      if (already) return Response.json({ claimed: false });
      await this.state.storage.put('setup', 1);
      await this.state.storage.setAlarm(Date.now() + RESULT_LIVES_FOR * 1000);
      return Response.json({ claimed: true });
    }

    if (action === 'peek') {
      // Whether something is waiting, without consuming it. For tests and for
      // a future status endpoint; nothing in the flow uses it.
      const found = await this.state.storage.get(KEY);
      return Response.json({ status: found ? found.status : 'pending' });
    }

    return Response.json({ error: 'no such action' }, { status: 404 });
  }

  async alarm() {
    await this.state.storage.deleteAll();
  }
}

/** The object for one flow, addressed by the nonce inside its signed state. */
function flowFor(env, nonce) {
  const id = env.CONNECTION_FLOW.idFromName(String(nonce));
  return env.CONNECTION_FLOW.get(id);
}

/**
 * Whether this deployment can hold a result at all.
 *
 * False on a deployment without the binding — which is what every version
 * before this one was. The receipt protocol still works there, so the answer
 * is to keep answering protocol 1 rather than to fail.
 */
export function available(env) {
  return Boolean(env && env.CONNECTION_FLOW);
}

/**
 * Ask one flow something.
 *
 * A `Request` rather than a URL string, which a stub would otherwise have to
 * construct itself. The runtime accepts either; being explicit means the
 * object receives the same thing in a test as it does in production.
 */
function ask(env, nonce, action, body) {
  const request = body === undefined
    ? new Request(`https://flow/${action}`)
    : new Request(`https://flow/${action}`, {
      method: 'POST',
      body: JSON.stringify(body),
      headers: { 'content-type': 'application/json' },
    });
  return flowFor(env, nonce).fetch(request);
}

/** Leave a finished result for the terminal that started this flow. */
export async function deliver(env, nonce, result) {
  return (await ask(env, nonce, 'deliver', result)).json();
}

/**
 * Collect it, once, for one request nonce.
 *
 * `requestNonce` is the one from the signed poll. Spending it here is what
 * stops a captured poll being replayed to take the result before the agent
 * that asked for it does.
 */
export async function take(env, nonce, requestNonce) {
  const answer = await ask(env, nonce, 'take', { nonce: String(requestNonce) });
  return { status: answer.status, body: await answer.json() };
}

/** What is waiting, without taking it. */
export async function peek(env, nonce) {
  return (await ask(env, nonce, 'peek')).json();
}

/** Arm a flow with the hash of its browser capability. */
export async function arm(env, nonce, digest, state, { now = Date.now() } = {}) {
  const answer = await ask(env, nonce, 'arm', {
    digest, state, expires: Math.floor(now / 1000) + LAUNCH_LIVES_FOR,
  });
  return (await answer.json()).armed === true;
}

/**
 * Spend it, once.
 *
 * `{ spent: false, why }` for gone, expired or wrong — the caller turns all
 * three into one answer, because distinguishing them tells a prober which
 * guess was closer.
 */
export async function spend(env, nonce, digest) {
  const answer = await ask(env, nonce, 'spend', { digest });
  return answer.json();
}

/**
 * Take the browser leg of a flow, if nobody has.
 *
 * False when somebody already has. See `claim-setup` above for why a flow may
 * only be walked through the browser once.
 */
export async function claimSetup(env, nonce) {
  const answer = await ask(env, nonce, 'claim-setup', {});
  return Boolean((await answer.json()).claimed);
}
