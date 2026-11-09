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

		it('throws on HTTP error instead of listing no channels', async () => {
			mockFetchFailure();
			await expect(getChannels()).rejects.toThrow('HTTP 500');
		});

		it('throws on network error', async () => {
			mockFetchReject();
			await expect(getChannels()).rejects.toThrow('network error');
		});
	});

	// -- createChannel --------------------------------------------------------

	// NET-224: a refusal carries the daemon's reason, so the page can say why
	describe('createChannel', () => {
		it('returns the channel on success', async () => {
			mockFetchSuccess({ id: 'ch1', type: 'slack', name: 'Slack' }, 201);
			const result = await createChannel('slack', 'Slack', { webhook_url: 'url' });
			expect(result).toEqual({ ok: true, data: { id: 'ch1', type: 'slack', name: 'Slack' } });
		});

		it("returns the daemon's reason when it refuses", async () => {
			mockFetchSuccess({ error: 'the URL must start with http:// or https://' }, 400);
			const result = await createChannel('webhook', 'Bad', { url: 'ftp://x' });
			expect(result).toEqual({ ok: false, error: 'the URL must start with http:// or https://' });
		});

		it('returns the status when the refusal has no reason', async () => {
			mockFetchFailure(500);
			expect(await createChannel('webhook', 'Bad', {})).toEqual({ ok: false, error: 'HTTP 500' });
		});

		it('says NetTap could not be reached on a network error', async () => {
			mockFetchReject();
			expect(await createChannel('discord', 'D', {})).toEqual({ ok: false, error: "couldn't reach NetTap" });
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
		it('reports success', async () => {
			mockFetchSuccess({ success: true });
			expect(await testChannel('ch1')).toEqual({ success: true });
		});

		it("reports a failure with the daemon's reason", async () => {
			mockFetchSuccess({ success: false, error: 'HTTP 404' });
			expect(await testChannel('ch1')).toEqual({ success: false, error: 'HTTP 404' });
		});

		it('reports a refused request with its reason', async () => {
			mockFetchSuccess({ error: 'Channel not found' }, 404);
			expect(await testChannel('gone')).toEqual({ success: false, error: 'Channel not found' });
		});

		it('reports a network error', async () => {
			mockFetchReject();
			expect(await testChannel('ch1')).toEqual({ success: false, error: "couldn't reach NetTap" });
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

		it('throws on error instead of an empty log', async () => {
			mockFetchFailure();
			await expect(getDeliveryLog()).rejects.toThrow('HTTP 500');
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

		it('throws on error instead of listing no rules', async () => {
			mockFetchFailure(503);
			await expect(getRules()).rejects.toThrow('HTTP 503');
		});
	});

	// -- createRule ------------------------------------------------------------

	describe('createRule', () => {
		it('returns the rule on success', async () => {
			const rule = { id: 'r1', event_type: 'alert', channels: ['ch1'], min_severity: 3 };
			mockFetchSuccess(rule, 201);
			expect(await createRule('alert', ['ch1'], 3)).toEqual({ ok: true, data: rule });
		});

		it("returns the daemon's reason when it refuses", async () => {
			mockFetchSuccess({ error: 'pick at least one channel' }, 400);
			expect(await createRule('alert', [], 3)).toEqual({ ok: false, error: 'pick at least one channel' });
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
