import { describe, it, expect, vi, beforeEach } from 'vitest';

const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a), RULE_UPDATE_TIMEOUT_MS: 290_000 }));

const commercial = await import('./rules/commercial/+server.js');
const update = await import('./rules/update/+server.js');
const custom = await import('./rules/custom/+server.js');
const customCheck = await import('./rules/custom/check/+server.js');

describe('Suricata API', () => {
	it('should have route handlers defined', () => {
		// API route tests require SvelteKit runtime context
		// Full integration tests are in e2e/
		// Covers: suricata/rules/*
		expect(true).toBe(true);
	});
});

/**
 * NET-191 slice 2: saving the ET Pro code and updating the rules can take minutes (the daemon checks the
 * code with Proofpoint, waits for the rules lock and restarts Suricata), past daemonFetch's 10 s default.
 */
describe('Suricata rule proxies', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
	});

	const answer = (status: number, body: unknown) => daemonFetch.mockResolvedValue(new Response(JSON.stringify(body), { status }));

	it('forwards the ET Pro code unchanged with 290 s, and passes the 202 through', async () => {
		answer(202, { saved: true, applying: true });
		const body = JSON.stringify({ code: 'abcd1234ABCD5678' });
		const request = new Request('http://localhost/api/suricata/rules/commercial', { method: 'POST', body });

		const res = await commercial.POST({ request } as never);

		expect(daemonFetch).toHaveBeenCalledWith('/api/suricata/rules/commercial', { method: 'POST', body }, 290_000);
		expect(res.status).toBe(202);
		expect(await res.json()).toEqual({ saved: true, applying: true });
	});

	it("passes a refused code's 400 and error text through", async () => {
		answer(400, { error: 'Proofpoint did not accept this code.' });
		const request = new Request('http://localhost/api/suricata/rules/commercial', { method: 'POST', body: '{"code":"x"}' });

		const res = await commercial.POST({ request } as never);

		expect(res.status).toBe(400);
		expect(await res.json()).toEqual({ error: 'Proofpoint did not accept this code.' });
	});

	it('removes the code with DELETE and 290 s, passing 202 and 409 through', async () => {
		answer(202, { cleared: true, applying: true });
		const res = await commercial.DELETE({} as never);

		expect(daemonFetch).toHaveBeenCalledWith('/api/suricata/rules/commercial', { method: 'DELETE' }, 290_000);
		expect(res.status).toBe(202);
		expect(await res.json()).toEqual({ cleared: true, applying: true });

		answer(409, { error: 'A rule update is running. Try again in a few minutes.' });
		const busy = await commercial.DELETE({} as never);
		expect(busy.status).toBe(409);
		expect(await busy.json()).toEqual({ error: 'A rule update is running. Try again in a few minutes.' });
	});

	it('reads the ET Pro status with the default timeout', async () => {
		answer(200, { configured: false, active: false, last_update_ok: null, applying: false, activation: null });

		const res = await commercial.GET({} as never);

		expect(daemonFetch).toHaveBeenCalledWith('/api/suricata/rules/commercial');
		expect(res.status).toBe(200);
	});

	it('gives a rule update 290 s and passes a 500 body through', async () => {
		const failed = { success: false, output: 'suricata-update exited 1', reload_output: '', status: { state: 'failed' } };
		answer(500, failed);

		const res = await update.POST({} as never);

		expect(daemonFetch).toHaveBeenCalledWith('/api/suricata/rules/update', { method: 'POST' }, 290_000);
		expect(res.status).toBe(500);
		expect(await res.json()).toEqual(failed);
	});
});

/** NET-191 slice 3: saving the owner rules runs Suricata's own test and a reload, up to about 4 minutes. */
describe('Owner rules proxies', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
	});

	const answer = (status: number, body: unknown) => daemonFetch.mockResolvedValue(new Response(JSON.stringify(body), { status }));
	const post = (path: string, body: string) => ({ request: new Request(`http://localhost${path}`, { method: 'POST', body }) }) as never;
	const BODY = JSON.stringify({ content: 'alert ip any any -> any any (msg:"x"; sid:1000001;)' });

	it('reads the owner rules with the default timeout', async () => {
		const rules = { content: '', rule_count: 0, max_rules: 2000, max_bytes: 262144 };
		answer(200, rules);

		const res = await custom.GET({} as never);

		expect(daemonFetch).toHaveBeenCalledWith('/api/suricata/rules/custom');
		expect(res.status).toBe(200);
		expect(await res.json()).toEqual(rules);
	});

	it('saves with 290 s, forwarding the body unchanged', async () => {
		answer(200, { saved: true, rule_count: 1, engine: { loaded: 65432, failed: 0 } });

		const res = await custom.POST(post('/api/suricata/rules/custom', BODY));

		expect(daemonFetch).toHaveBeenCalledWith('/api/suricata/rules/custom', { method: 'POST', body: BODY }, 290_000);
		expect(res.status).toBe(200);
		expect(await res.json()).toEqual({ saved: true, rule_count: 1, engine: { loaded: 65432, failed: 0 } });
	});

	it.each([
		[400, { error: 'One line needs fixing.', errors: [{ line: 1, message: 'Only alert rules can be used.' }] }],
		[409, { error: 'A Suricata rule update is running. Try again in a few minutes.' }],
		[422, { error: 'Suricata refused the rules: bad option', errors: [] }],
		[502, { error: "Suricata didn't reload. The previous rules were put back." }],
	])("passes a save's %i and body through", async (status, body) => {
		answer(status, body);

		const res = await custom.POST(post('/api/suricata/rules/custom', BODY));

		expect(res.status).toBe(status);
		expect(await res.json()).toEqual(body);
	});

	it('checks with the default timeout and passes a 400 with line reasons through', async () => {
		const refused = { error: 'One line needs fixing.', errors: [{ line: 3, message: 'Only alert rules can be used.' }] };
		answer(400, refused);

		const res = await customCheck.POST(post('/api/suricata/rules/custom/check', BODY));

		expect(daemonFetch).toHaveBeenCalledWith('/api/suricata/rules/custom/check', { method: 'POST', body: BODY });
		expect(res.status).toBe(400);
		expect(await res.json()).toEqual(refused);
	});

	it("says so when the daemon's reply isn't JSON", async () => {
		daemonFetch.mockResolvedValue(new Response('<html>', { status: 502 }));

		const res = await customCheck.POST(post('/api/suricata/rules/custom/check', BODY));

		expect(res.status).toBe(502);
		expect(await res.json()).toEqual({ error: 'Failed to parse daemon response' });
	});
});
