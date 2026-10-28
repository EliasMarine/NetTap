import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getChannels,
	createChannel,
	deleteChannel,
	testChannel,
	getDeliveryLog,
	getRules,
	createRule,
	deleteRule,
} from './notification-hub';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(body: unknown, status = 200): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: status >= 200 && status < 300,
			status,
			json: () => Promise.resolve(body),
		}),
	);
}

function mockFetchFailure(status = 500): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.reject(new Error('no body')),
		}),
	);
}

function mockFetchReject(): void {
	vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network error')));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('notification-hub API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getChannels ----------------------------------------------------------

	describe('getChannels', () => {
		it('returns channels on success', async () => {
			mockFetchSuccess({
				channels: [{ id: 'ch1', type: 'discord', name: 'Discord' }],
				count: 1,
			});
			const result = await getChannels();
			expect(result.count).toBe(1);
			expect(result.channels[0].type).toBe('discord');
		});

		it('returns empty on HTTP error', async () => {
			mockFetchFailure();
			const result = await getChannels();
			expect(result.channels).toEqual([]);
		});

		it('returns empty on network error', async () => {
			mockFetchReject();
			const result = await getChannels();
			expect(result.channels).toEqual([]);
		});
	});

	// -- createChannel --------------------------------------------------------

	describe('createChannel', () => {
		it('returns channel on success', async () => {
			mockFetchSuccess({ id: 'ch1', type: 'slack', name: 'Slack' }, 201);
			const result = await createChannel('slack', 'Slack', { webhook_url: 'url' });
			expect(result).not.toBeNull();
			expect(result!.type).toBe('slack');
		});

		it('returns null on error', async () => {
			mockFetchFailure(400);
			const result = await createChannel('invalid', 'Bad', {});
			expect(result).toBeNull();
		});

		it('returns null on network error', async () => {
			mockFetchReject();
			const result = await createChannel('discord', 'D', {});
			expect(result).toBeNull();
		});
	});

	// -- deleteChannel --------------------------------------------------------

	describe('deleteChannel', () => {
		it('returns true on success', async () => {
			mockFetchSuccess({ deleted: true });
			expect(await deleteChannel('ch1')).toBe(true);
		});

		it('returns false on error', async () => {
			mockFetchFailure(404);
			expect(await deleteChannel('nope')).toBe(false);
		});

		it('returns false on network error', async () => {
			mockFetchReject();
			expect(await deleteChannel('ch1')).toBe(false);
		});
	});

	// -- testChannel ----------------------------------------------------------

	describe('testChannel', () => {
		it('returns true on success', async () => {
			mockFetchSuccess({ success: true });
			expect(await testChannel('ch1')).toBe(true);
		});

		it('returns false on failure response', async () => {
			mockFetchSuccess({ success: false });
			expect(await testChannel('ch1')).toBe(false);
		});

		it('returns false on network error', async () => {
			mockFetchReject();
			expect(await testChannel('ch1')).toBe(false);
		});
	});

	// -- getDeliveryLog -------------------------------------------------------

	describe('getDeliveryLog', () => {
		it('returns log entries on success', async () => {
			mockFetchSuccess({
				log: [{ channel_id: 'ch1', success: true, timestamp: '2026-03-08T00:00:00Z' }],
				count: 1,
			});
			const result = await getDeliveryLog();
			expect(result.count).toBe(1);
		});

		it('returns empty on error', async () => {
			mockFetchFailure();
			const result = await getDeliveryLog();
			expect(result.log).toEqual([]);
		});
	});

	// -- getRules -------------------------------------------------------------

	describe('getRules', () => {
		it('returns rules on success', async () => {
			mockFetchSuccess({
				rules: [{ id: 'r1', event_type: 'alert', channels: ['ch1'] }],
				count: 1,
			});
			const result = await getRules();
			expect(result.count).toBe(1);
		});

		it('returns empty on error', async () => {
			mockFetchReject();
			const result = await getRules();
			expect(result.rules).toEqual([]);
		});
	});

	// -- createRule ------------------------------------------------------------

	describe('createRule', () => {
		it('returns rule on success', async () => {
			mockFetchSuccess({ id: 'r1', event_type: 'alert', channels: ['ch1'], min_severity: 3 }, 201);
			const result = await createRule('alert', ['ch1'], 3);
			expect(result).not.toBeNull();
			expect(result!.event_type).toBe('alert');
		});

		it('returns null on error', async () => {
			mockFetchFailure(400);
			const result = await createRule('invalid', [], 0);
			expect(result).toBeNull();
		});
	});

	// -- deleteRule ------------------------------------------------------------

	describe('deleteRule', () => {
		it('returns true on success', async () => {
			mockFetchSuccess({ deleted: true });
			expect(await deleteRule('r1')).toBe(true);
		});

		it('returns false on error', async () => {
			mockFetchFailure(404);
			expect(await deleteRule('nope')).toBe(false);
		});
	});
});
