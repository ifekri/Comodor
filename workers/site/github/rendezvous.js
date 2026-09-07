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

import { RESULT_LIVES_FOR } from './config.js';

const KEY = 'result';

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
      const found = await this.state.storage.get(KEY);
      if (!found) return Response.json({ status: 'pending' });
      // Read once and gone. The terminal saves what it collects, and leaving
      // a copy behind would keep a grant readable by a second caller that
      // manages to sign correctly — which the key holder can, but only they,
      // and only until they have what they asked for.
      await this.state.storage.delete(KEY);
      return Response.json(found);
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

/** Collect it, once. `{ status: 'pending' }` while the browser is still out. */
export async function take(env, nonce) {
  return (await ask(env, nonce, 'take')).json();
}

/** What is waiting, without taking it. */
export async function peek(env, nonce) {
  return (await ask(env, nonce, 'peek')).json();
}
