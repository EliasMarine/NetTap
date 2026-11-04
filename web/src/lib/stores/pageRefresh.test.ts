import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { createLoadGuard, registerPageRefresh, refreshPage, pageRefresh, outcome, type LoadResult } from './pageRefresh';

function deferred<T>() {
	let resolve!: (v: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

let clock = 1000;
const now = () => clock;

beforeEach(() => {
	clock = 1000;
	// leave no page registered between tests
	registerPageRefresh(async () => 'skipped').unregister();
});

describe('createLoadGuard', () => {
	it('only the newest generation is current', () => {
		const g = createLoadGuard();
		const a = g.begin();
		const b = g.begin();
		expect(g.current(a)).toBe(false);
		expect(g.current(b)).toBe(true);
	});

	it('invalidate stops every generation, including future ones', () => {
		const g = createLoadGuard();
		const a = g.begin();
		g.invalidate();
		expect(g.current(a)).toBe(false);
		expect(g.current(g.begin())).toBe(false);
	});
});

describe('registerPageRefresh', () => {
	it('advances updatedAt only on ok', async () => {
		const results: LoadResult[] = ['ok', 'partial', 'failed', 'skipped'];
		let i = 0;
		const h = registerPageRefresh(async () => results[i++], now);
		await h.run();
		expect(get(pageRefresh)).toMatchObject({ updatedAt: 1000, status: 'ok' });
		clock = 2000;
		await h.run();
		expect(get(pageRefresh)).toMatchObject({ updatedAt: 1000, status: 'partial' });
		await h.run();
		expect(get(pageRefresh)).toMatchObject({ updatedAt: 1000, status: 'failed' });
		await h.run();
		expect(get(pageRefresh)).toMatchObject({ updatedAt: 1000, status: 'failed' });
		h.unregister();
	});

	it('a throwing loader counts as failed', async () => {
		const h = registerPageRefresh(async () => {
			throw new Error('boom');
		}, now);
		expect(await h.run()).toBe('failed');
		expect(get(pageRefresh).status).toBe('failed');
		h.unregister();
	});

	it('refreshPage calls the current page loader once', async () => {
		let calls = 0;
		const h = registerPageRefresh(async () => {
			calls++;
			return 'ok';
		}, now);
		await refreshPage();
		expect(calls).toBe(1);
		h.unregister();
		expect(await refreshPage()).toBe('skipped');
		expect(calls).toBe(1);
	});

	it('reversed completion: the older load writes nothing', async () => {
		const shown: string[] = [];
		const slow = deferred<string>();
		const fast = deferred<string>();
		const queue = [slow, fast];
		const h = registerPageRefresh(async (guard) => {
			const g = guard.begin();
			const data = await queue.shift()!.promise;
			if (!guard.current(g)) return 'skipped';
			shown.push(data);
			return 'ok';
		}, now);
		const first = h.run();
		const second = h.run();
		fast.resolve('1h');
		expect(await second).toBe('ok');
		slow.resolve('24h');
		expect(await first).toBe('skipped');
		expect(shown).toEqual(['1h']);
		expect(get(pageRefresh).running).toBe(false);
		h.unregister();
	});

	it('navigation before completion: no writes and no timestamp change', async () => {
		const shown: string[] = [];
		const pending = deferred<string>();
		const h = registerPageRefresh(async (guard) => {
			const g = guard.begin();
			const data = await pending.promise;
			if (!guard.current(g)) return 'skipped';
			shown.push(data);
			return 'ok';
		}, now);
		const run = h.run();
		h.unregister();
		const next = registerPageRefresh(async () => 'skipped', now);
		pending.resolve('late');
		await run;
		expect(shown).toEqual([]);
		expect(get(pageRefresh)).toMatchObject({ available: true, updatedAt: null, status: null });
		next.unregister();
		expect(get(pageRefresh).available).toBe(false);
	});
});

describe('outcome', () => {
	const ok: PromiseSettledResult<number> = { status: 'fulfilled', value: 1 };
	const no: PromiseSettledResult<number> = { status: 'rejected', reason: new Error('HTTP 503') };
	it('is ok when every request succeeded', () => expect(outcome([ok, ok])).toBe('ok'));
	it('is partial when some failed', () => expect(outcome([ok, no])).toBe('partial'));
	it('is failed when all failed', () => expect(outcome([no, no])).toBe('failed'));
});
