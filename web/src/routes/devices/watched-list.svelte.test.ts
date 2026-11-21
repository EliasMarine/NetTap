import { describe, it, expect, vi, afterEach } from 'vitest';
import { getWatchedDevices, type WatchedDevicesResponse } from '$api/devices-watched';
import { WatchedList } from './watched-list.svelte';

vi.mock('$api/devices-watched', () => ({ getWatchedDevices: vi.fn() }));

const reply = (n: number): WatchedDevicesResponse => ({
	check: { attempt_at: null, success_at: null, capture_at: null, coverage_since: null, skipped: null, error: null },
	devices: Array.from({ length: n }, (_, i) => ({ mac: `AA:BB:CC:00:00:0${i}`, name: null, after_min: 15, state: 'up' as const, seen_at: null, since: null })),
});

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => ((resolve = res), (reject = rej)));
	return { promise, resolve, reject };
}

describe('WatchedList (NET-331)', () => {
	afterEach(() => vi.clearAllMocks());

	it('keeps the newest read when an older one lands after it', async () => {
		const older = deferred<WatchedDevicesResponse>();
		vi.mocked(getWatchedDevices).mockReturnValueOnce(older.promise).mockResolvedValueOnce(reply(2));
		const list = new WatchedList();
		const first = list.load();
		await list.load();
		older.resolve(reply(5));
		await first;
		expect(list.data?.devices).toHaveLength(2);
	});

	it('keeps the last list on a failed read, with the reason, and rejects so the page counts it', async () => {
		vi.mocked(getWatchedDevices).mockResolvedValueOnce(reply(1)).mockRejectedValueOnce(new Error('The device details file is unreadable.'));
		const list = new WatchedList();
		await list.load();
		await expect(list.load()).rejects.toThrow('The device details file is unreadable.');
		expect(list.data?.devices).toHaveLength(1);
		expect(list.error).toBe('The device details file is unreadable.');
	});

	it("an older failure doesn't mark a newer success as failed", async () => {
		const older = deferred<WatchedDevicesResponse>();
		vi.mocked(getWatchedDevices).mockReturnValueOnce(older.promise).mockResolvedValueOnce(reply(1));
		const list = new WatchedList();
		const first = list.load();
		await list.load();
		older.reject(new Error('late'));
		await expect(first).rejects.toThrow('late');
		expect(list.error).toBeNull();
	});

	it('reload never rejects: the card shows the failure', async () => {
		vi.mocked(getWatchedDevices).mockRejectedValueOnce(new Error('down'));
		const list = new WatchedList();
		await expect(list.reload()).resolves.toBeUndefined();
		expect(list.error).toBe('down');
	});
});
