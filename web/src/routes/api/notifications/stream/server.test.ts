import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

/**
 * The live notification stream (NET-358): it checks its session again before every write, so a
 * stream whose session a password change ended closes at its next notification or keepalive and
 * sends nothing more. Real auth and user store; the notification source is a stand-in.
 */

const subscribers = vi.hoisted(() => new Set<(notification: unknown) => void>());
vi.mock('$lib/server/notifications.js', () => ({
	onNotification: (callback: (notification: unknown) => void) => {
		subscribers.add(callback);
		return () => subscribers.delete(callback);
	},
}));

type Get = typeof import('./+server').GET;

let dataDir: string;
let GET: Get;
let auth: typeof import('$lib/server/auth.js');

const decoder = new TextDecoder();
const notify = (notification: unknown) => [...subscribers].forEach((callback) => callback(notification));
const storeWithHash = (passwordHash: string) =>
	writeFileSync(
		join(dataDir, 'users.json'),
		JSON.stringify({ users: [{ username: 'alice', passwordHash, role: 'admin', createdAt: '', updatedAt: '' }] })
	);

async function open(token: string, signal = new AbortController().signal) {
	const request = new Request('http://localhost/api/notifications/stream', { signal });
	const cookies = { get: (name: string) => (name === 'nettap_token' ? token : undefined) };
	const res = await GET({ request, cookies } as unknown as Parameters<Get>[0]);
	const reader = res.body!.getReader();
	const next = async () => {
		const { done, value } = await reader.read();
		return done ? null : decoder.decode(value);
	};
	expect(await next()).toBe(': connected\n\n');
	return next;
}

beforeEach(async () => {
	dataDir = mkdtempSync(join(tmpdir(), 'nettap-stream-'));
	vi.stubEnv('DATA_DIR', dataDir);
	vi.stubEnv('JWT_SECRET', '');
	vi.resetModules();
	subscribers.clear();
	auth = await import('$lib/server/auth.js');
	({ GET } = await import('./+server'));
	storeWithHash('hash-1');
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllEnvs();
	rmSync(dataDir, { recursive: true, force: true });
});

const session = () => auth.generateToken({ username: 'alice', role: 'admin', passwordHash: 'hash-1' });

describe('GET /api/notifications/stream', () => {
	it('sends notifications while the session is valid', async () => {
		const next = await open(session());
		notify({ id: 'n1', title: 'New alert' });
		expect(await next()).toBe(`event: notification\ndata: ${JSON.stringify({ id: 'n1', title: 'New alert' })}\n\n`);
	});

	it('closes before the next notification once a password change ended the session, and sends nothing after', async () => {
		const next = await open(session());

		storeWithHash('hash-2'); // the password changed in another browser
		notify({ id: 'n2', signature: 'ET SCAN something' });

		expect(await next()).toBeNull();
		expect(subscribers.size).toBe(0);
		notify({ id: 'n3' }); // nothing listens any more
	});

	it('closes at the next keepalive when no notification comes', async () => {
		vi.useFakeTimers();
		const next = await open(session());

		await vi.advanceTimersByTimeAsync(30_000);
		expect(await next()).toBe(': keepalive\n\n');

		storeWithHash('hash-2');
		await vi.advanceTimersByTimeAsync(30_000);
		expect(await next()).toBeNull();
		expect(subscribers.size).toBe(0);
		expect(vi.getTimerCount()).toBe(0);
	});

	it('stops when the client disconnects', async () => {
		const abort = new AbortController();
		const next = await open(session(), abort.signal);
		abort.abort();
		expect(await next()).toBeNull();
		expect(subscribers.size).toBe(0);
	});
});
