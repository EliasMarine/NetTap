/**
 * Fixture daemon for the visual harness (PLAN.md §5.2).
 *
 * Run with `node --experimental-strip-types e2e/visual/fixture-daemon.ts`, so only
 * erasable TypeScript is allowed here and in the fixtures. It stands in for
 * nettap-storage-daemon: the web server's daemonFetch() calls it through DAEMON_URL.
 */
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { readFileSync } from 'node:fs';
import { ROUTES } from './fixtures/index.ts';
import type { FixtureRoute } from './fixtures/types.ts';

// Stale data is a sequence, not a mode: load in `populated`, switch to `error`, refresh (harness.ts).
const MODES = ['populated', 'empty', 'error', 'slow'] as const;
type Mode = (typeof MODES)[number];

const PORT = Number(process.env.FIXTURE_DAEMON_PORT ?? 3199);
const TOKEN_HEADER = 'x-nettap-daemon-token';
const tokenFile = process.env.DAEMON_TOKEN_FILE;
if (!tokenFile) throw new Error('DAEMON_TOKEN_FILE is required');
const expectedToken = readFileSync(tokenFile, 'utf-8').trim();

let mode: Mode = 'empty';
/** `slow` mode parks each response here until POST /__fixture/release, so tests check the loading state while it lasts. */
let held: Array<() => void> = [];

function release(): number {
	const n = held.length;
	held.forEach((send) => send());
	held = [];
	return n;
}

function send(res: ServerResponse, status: number, body: unknown): void {
	res.writeHead(status, { 'Content-Type': 'application/json' });
	res.end(JSON.stringify(body));
}

/** Exact paths win over patterns, so /api/devices/count is never taken for a device id. */
function findRoute(method: string, pathname: string): FixtureRoute | undefined {
	const candidates = ROUTES.filter((r) => !r.method || r.method === method);
	return (
		candidates.find((r) => r.path === pathname) ??
		candidates.find((r) => r.path instanceof RegExp && r.path.test(pathname))
	);
}

function bodyFor(route: FixtureRoute, m: Mode): unknown {
	return m === 'empty' ? route.empty : (route.populated ?? route.empty);
}

async function readBody(req: IncomingMessage): Promise<string> {
	let data = '';
	for await (const chunk of req) data += chunk;
	return data;
}

async function control(req: IncomingMessage, res: ServerResponse, pathname: string): Promise<void> {
	if (pathname === '/__fixture/health') return send(res, 200, { status: 'ok', mode, held: held.length });
	if (pathname === '/__fixture/release' && req.method === 'POST') return send(res, 200, { released: release() });
	if (pathname === '/__fixture/mode' && req.method === 'POST') {
		let requested: unknown;
		try {
			requested = (JSON.parse(await readBody(req)) as { mode?: unknown }).mode;
		} catch {
			return send(res, 400, { error: 'body must be JSON {"mode": ...}' });
		}
		if (!MODES.includes(requested as Mode)) {
			return send(res, 400, { error: `mode must be one of ${MODES.join(', ')}` });
		}
		release(); // a mode change never strands a parked response
		mode = requested as Mode;
		return send(res, 200, { mode });
	}
	send(res, 404, { error: `unknown control path ${pathname}` });
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
	const method = req.method ?? 'GET';
	const { pathname } = new URL(req.url ?? '/', 'http://fixture');

	if (pathname.startsWith('/__fixture/')) return control(req, res, pathname);

	// The real daemon rejects a missing or wrong token before any handler runs.
	if (req.headers[TOKEN_HEADER] !== expectedToken) {
		console.error(`[fixture-daemon] 401 ${method} ${pathname}: token header missing or wrong`);
		return send(res, 401, { error: 'Unauthorized' });
	}

	const route = findRoute(method, pathname);
	if (!route) console.error(`[fixture-daemon] MISSING FIXTURE ${method} ${pathname} (mode ${mode})`);
	if (mode === 'error') return send(res, 503, { error: 'Service unavailable (fixture error mode)' });
	if (!route) return send(res, 404, { error: `No fixture for ${method} ${pathname}` });
	const body = bodyFor(route, mode);
	if (mode === 'slow') {
		held = [...held, () => send(res, 200, body)];
		return;
	}
	send(res, 200, body);
}

createServer((req, res) => {
	handle(req, res).catch((err: unknown) => {
		console.error('[fixture-daemon] handler failed', err);
		if (!res.headersSent) send(res, 500, { error: 'fixture daemon failure' });
	});
}).listen(PORT, '127.0.0.1', () => {
	console.error(`[fixture-daemon] listening on 127.0.0.1:${PORT}, ${ROUTES.length} routes`);
});
