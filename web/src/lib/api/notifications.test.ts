import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getNotifications,
	markNotificationRead,
	markAllNotificationsRead,
} from './notifications';

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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('notifications API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getNotifications ----------------------------------------------------

	describe('getNotifications', () => {
		it('returns notifications and unread count on success', async () => {
			const expected = {
				notifications: [
					{
						id: 'ntf_1',
						type: 'alert',
						severity: 'high',
						title: 'Suspicious traffic',
						message: 'Detected outbound traffic to known C2 server.',
						timestamp: '2026-02-26T12:00:00Z',
						read: false,
					},
				],
				unreadCount: 1,
			};
			mockFetchSuccess(expected);

			const result = await getNotifications(10);

			expect(fetch).toHaveBeenCalledWith('/api/notifications?limit=10');
			expect(result.notifications).toHaveLength(1);
			expect(result.unreadCount).toBe(1);
		});

		it('returns empty on HTTP error', async () => {
			mockFetchFailure(500);

			const result = await getNotifications();

			expect(result.notifications).toEqual([]);
			expect(result.unreadCount).toBe(0);
		});
	});

	// -- markNotificationRead -----------------------------------------------

	describe('markNotificationRead', () => {
		it('sends POST with markRead action', async () => {
			mockFetchSuccess({ success: true });

			const result = await markNotificationRead('ntf_1');

			expect(result).toBe(true);
			expect(fetch).toHaveBeenCalledWith('/api/notifications', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ action: 'markRead', id: 'ntf_1' }),
			});
		});

		it('returns false on failure', async () => {
			mockFetchFailure(404);

			const result = await markNotificationRead('ntf_missing');

			expect(result).toBe(false);
		});
	});

	// -- markAllNotificationsRead -------------------------------------------

	describe('markAllNotificationsRead', () => {
		it('sends POST with markAllRead action', async () => {
			mockFetchSuccess({ success: true, markedCount: 5 });

			const result = await markAllNotificationsRead();

			expect(result).toBe(true);
			expect(fetch).toHaveBeenCalledWith('/api/notifications', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ action: 'markAllRead' }),
			});
		});

		it('returns false on failure', async () => {
			mockFetchFailure(500);

			const result = await markAllNotificationsRead();

			expect(result).toBe(false);
		});
	});
});
