import { describe, it, expect, vi, beforeEach } from 'vitest';

type Module = typeof import('./password-change');
let pc: Module;

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (err: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const reply = (status: number) => new Response('{}', { status });

beforeEach(async () => {
	vi.resetModules(); // the module holds page-wide state
	pc = await import('./password-change');
});

describe('password change tracking (NET-358)', () => {
	it('is settled at once with nothing in flight', async () => {
		await expect(pc.passwordChangeSettled()).resolves.toBeUndefined();
		expect(pc.passwordChangeCount()).toBe(0);
	});

	it('counts a change only when it succeeds, before the caller sees the result', async () => {
		const accepted = reply(200);
		expect(await pc.trackPasswordChange(Promise.resolve(accepted))).toBe(accepted);
		expect(pc.passwordChangeCount()).toBe(1);

		await pc.trackPasswordChange(Promise.resolve(reply(400)));
		expect(pc.passwordChangeCount()).toBe(1);
	});

	it('passes a failed request on to the caller without counting it', async () => {
		await expect(pc.trackPasswordChange(Promise.reject(new Error('offline')))).rejects.toThrow('offline');
		expect(pc.passwordChangeCount()).toBe(0);
		await expect(pc.passwordChangeSettled()).resolves.toBeUndefined();
	});

	it('waits for a change in flight, and the count has moved when the wait ends', async () => {
		const request = deferred<Response>();
		void pc.trackPasswordChange(request.promise);
		let settled = false;
		void pc.passwordChangeSettled().then(() => (settled = true));

		await flush();
		expect(settled).toBe(false);

		request.resolve(reply(200));
		await flush();
		expect(settled).toBe(true);
		expect(pc.passwordChangeCount()).toBe(1);
	});

	it.each([
		['fails', new TypeError('Failed to fetch')],
		['is aborted by its timeout', new DOMException('The operation timed out.', 'TimeoutError')],
	])('never rejects while waiting, and settles, when the change %s', async (_, err) => {
		const request = deferred<Response>();
		const tracked = pc.trackPasswordChange(request.promise);
		const wait = pc.passwordChangeSettled();
		request.reject(err);
		await expect(tracked).rejects.toBe(err);
		await expect(wait).resolves.toBeUndefined();
		expect(pc.passwordChangeCount()).toBe(0);
	});

	it('waits for a change that starts while it is already waiting', async () => {
		const first = deferred<Response>();
		const second = deferred<Response>();
		void pc.trackPasswordChange(first.promise);
		let settled = false;
		void pc.passwordChangeSettled().then(() => (settled = true));
		void pc.trackPasswordChange(second.promise);

		first.resolve(reply(200));
		await flush();
		expect(settled).toBe(false);

		second.resolve(reply(200));
		await flush();
		expect(settled).toBe(true);
		expect(pc.passwordChangeCount()).toBe(2);
	});
});
