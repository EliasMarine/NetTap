import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$api/alerts', () => ({ getAlertCount: vi.fn() }));

import {
	_configure,
	alertSnapshots,
	loadAlertSnapshot,
	refreshAlertSnapshots,
	snapshotWindow,
} from './alertSnapshot';

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((r, j) => ((resolve = r), (reject = j)));
	return { promise, resolve, reject };
}

const counts = (total: number) => ({ from: '', to: '', counts: { total, high: 0, medium: 0, low: 0 } });

let clock = Date.parse('2026-11-03T21:05:42.123Z');

beforeEach(() => {
	clock = Date.parse('2026-11-03T21:05:42.123Z');
});

describe('snapshotWindow', () => {
	it('is rounded down to the minute', () => {
		expect(snapshotWindow(24, clock)).toEqual({
			from: '2026-11-02T21:05:00.000Z',
			to: '2026-11-03T21:05:00.000Z',
		});
	});
});

describe('alert snapshot', () => {
	it('shares one request between concurrent callers, with identical windows', async () => {
		const fetcher = vi.fn(async () => counts(37));
		_configure({ fetcher, now: () => clock });
		const [a, b] = await Promise.all([loadAlertSnapshot(24), loadAlertSnapshot(24)]);
		expect(fetcher).toHaveBeenCalledTimes(1);
		expect(a).toBe(b);
		expect(get(alertSnapshots)[24].data!.counts.total).toBe(37);
	});

	it('drops a response from an older generation', async () => {
		const slow = deferred<ReturnType<typeof counts>>();
		const fast = deferred<ReturnType<typeof counts>>();
		const queue = [slow, fast];
		_configure({ fetcher: () => queue.shift()!.promise, now: () => clock });
		const first = loadAlertSnapshot(24);
		clock += 60_000;
		const second = refreshAlertSnapshots();
		fast.resolve(counts(40));
		await second;
		slow.resolve(counts(12));
		await first;
		expect(get(alertSnapshots)[24].data!.counts.total).toBe(40);
	});

	it('a refresh moves every reader to the new generation and window', async () => {
		let n = 30;
		_configure({ fetcher: async () => counts(n++), now: () => clock });
		await loadAlertSnapshot(24);
		const before = get(alertSnapshots)[24];
		clock += 5 * 60_000;
		await refreshAlertSnapshots();
		const after = get(alertSnapshots)[24];
		expect(after.data!.counts.total).toBe(31);
		expect(after.to > before.to).toBe(true);
	});

	it('keeps other windows separate', async () => {
		const fetcher = vi.fn(async (p: { from: string; to: string }) =>
			counts(Date.parse(p.to) - Date.parse(p.from) > 3_600_000 ? 37 : 2),
		);
		_configure({ fetcher, now: () => clock });
		await Promise.all([loadAlertSnapshot(24), loadAlertSnapshot(1)]);
		expect(get(alertSnapshots)[24].data!.counts.total).toBe(37);
		expect(get(alertSnapshots)[1].data!.counts.total).toBe(2);
	});

	it('records a failure as an error state, never a number', async () => {
		_configure({
			fetcher: async () => {
				throw new Error('503');
			},
			now: () => clock,
		});
		const snap = await loadAlertSnapshot(24);
		expect(snap).toMatchObject({ status: 'error', data: null });
	});

	it('keeps the last good counts through a failed refresh, marked as an error', async () => {
		let fail = false;
		_configure({
			fetcher: async () => {
				if (fail) throw new Error('503');
				return counts(37);
			},
			now: () => clock,
		});
		await loadAlertSnapshot(24);
		fail = true;
		const [snap] = await refreshAlertSnapshots();
		expect(snap.status).toBe('error');
		expect(snap.data!.counts.total).toBe(37);
	});
});
