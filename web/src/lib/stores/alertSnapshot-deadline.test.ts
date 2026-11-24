/**
 * NET-361: the store's own fetcher (the real getAlertCount) gives every count a deadline, so a stalled count
 * can't outlive the shell's 30 s refresh. Its own file: alertSnapshot.test.ts mocks $api/alerts for the module.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { alertSnapshots, loadAlertSnapshot, refreshAlertSnapshots } from './alertSnapshot';

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('alert snapshot deadline', () => {
	it('gives up on a count after 15 s and asks again on the next refresh', async () => {
		vi.useFakeTimers();
		// AbortSignal.timeout on the fake clock: Node's own timer doesn't follow vi.useFakeTimers
		vi.spyOn(AbortSignal, 'timeout').mockImplementation((ms) => {
			const controller = new AbortController();
			setTimeout(() => controller.abort(new DOMException('The operation timed out.', 'TimeoutError')), ms);
			return controller.signal;
		});
		const fetchMock = vi.fn(
			(_url: string, init?: RequestInit) =>
				new Promise<Response>((_, reject) => init?.signal?.addEventListener('abort', () => reject(init.signal?.reason))),
		);
		vi.stubGlobal('fetch', fetchMock);

		void loadAlertSnapshot(24);
		await vi.advanceTimersByTimeAsync(14_999);
		expect(get(alertSnapshots)[24]?.status).toBe('loading');

		await vi.advanceTimersByTimeAsync(1);
		expect(get(alertSnapshots)[24]?.status).toBe('error');

		void refreshAlertSnapshots();
		expect(fetchMock).toHaveBeenCalledTimes(2);
	});
});
