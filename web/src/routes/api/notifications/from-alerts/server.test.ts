import { describe, it, expect, vi, beforeEach } from 'vitest';

// NET-224 P2: the bell calls this on every page load; it must say when the daemon failed, and the
// store (now on disk) must not fill with the same alert batch again and again
const daemonFetch = vi.fn();
vi.mock('$lib/server/daemon.js', () => ({ daemonFetch: (...a: unknown[]) => daemonFetch(...a) }));

const stored: Array<Record<string, unknown>> = [];
const sendNotification = vi.fn(async (n: Record<string, unknown>) => {
	const full = { ...n, id: String(stored.length), timestamp: new Date().toISOString(), read: false };
	stored.unshift(full);
	return full;
});
vi.mock('$lib/server/notifications.js', () => ({
	MAX_STORED_NOTIFICATIONS: 200,
	getNotifications: (limit: number) => stored.slice(0, limit),
	sendNotification: (n: Record<string, unknown>) => sendNotification(n),
}));

const { GET } = await import('./+server');

const ALERTS = {
	alerts: [
		{ category_label: 'Malware & C2', signature: 'ET TEST signature 1', severity: 1, count: 3, source_ip: '192.0.2.10', destination_ip: '192.0.2.20' },
		{ category_label: 'Policy', signature: 'ET TEST signature 2', severity: 3, count: 1 },
	],
};

function answer(status: number, body: unknown) {
	daemonFetch.mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

describe('GET /api/notifications/from-alerts', () => {
	beforeEach(() => {
		daemonFetch.mockReset();
		sendNotification.mockClear();
		stored.length = 0;
	});

	it("answers 502 with the daemon's reason instead of \"0 created\"", async () => {
		answer(502, { error: 'Daemon unreachable: connect ECONNREFUSED' });

		const res = await GET();

		expect(res.status).toBe(502);
		expect((await res.json()).error).toBe("Couldn't read the alerts: Daemon unreachable: connect ECONNREFUSED");
		expect(sendNotification).not.toHaveBeenCalled();
	});

	// Visual error mode: the web server's own 502 is a bug; the daemon's status passes through, as the proxy does
	it("passes the daemon's own error status on, with its reason", async () => {
		answer(503, { error: 'OpenSearch unavailable' });

		const res = await GET();

		expect(res.status).toBe(503);
		expect((await res.json()).error).toBe("Couldn't read the alerts: OpenSearch unavailable");
	});

	it('answers 502 when the daemon says OK but the body is unreadable', async () => {
		daemonFetch.mockResolvedValue(new Response('not json', { status: 200 }));

		const res = await GET();

		expect(res.status).toBe(502);
		expect((await res.json()).error).toBe("Couldn't read the alerts: HTTP 200");
	});

	it('creates a critical or high batch once a day, not on every page load', async () => {
		answer(200, ALERTS);
		expect(await (await GET()).json()).toMatchObject({ notifications_created: 1 });
		expect(sendNotification.mock.calls[0][0]).toMatchObject({ source: { category: 'Malware & C2', signature: 'ET TEST signature 1' } });

		answer(200, ALERTS);
		expect(await (await GET()).json()).toMatchObject({ notifications_created: 0 });
		expect(sendNotification).toHaveBeenCalledTimes(1);

		stored[0].timestamp = new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString();
		answer(200, ALERTS);
		expect(await (await GET()).json()).toMatchObject({ notifications_created: 1 });
	});
});
