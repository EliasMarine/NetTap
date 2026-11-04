import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import NotificationBell from './NotificationBell.svelte';

vi.mock('$api/notification-stream', () => ({
	createNotificationStream: vi.fn(() => ({ close: vi.fn(), isConnected: () => true })),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

const NOTE = {
	id: 'ntf_1', type: 'alert', severity: 'high', title: 'Port scan from 10.0.0.9',
	message: 'Many ports probed', timestamp: '2026-11-02T09:00:00Z', read: false,
};

/** /api/notifications answers from `reply()`; the alert-conversion call always succeeds. */
function stubFetch(reply: () => { ok: boolean; status: number; body: unknown }) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			if (url.startsWith('/api/notifications?')) {
				const r = reply();
				return { ok: r.ok, status: r.status, json: async () => r.body };
			}
			return { ok: true, status: 200, json: async () => ({}) };
		}),
	);
}

async function openBell() {
	render(NotificationBell);
	await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/notifications?limit=15'));
	await new Promise((r) => setTimeout(r, 0));
	await fireEvent.click(screen.getByRole('button', { name: /^Notifications/ }));
}

describe('NotificationBell when the request fails (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says notifications could not be loaded instead of "No notifications"', async () => {
		stubFetch(() => ({ ok: false, status: 500, body: {} }));
		await openBell();

		expect(await screen.findByText("Couldn't load notifications: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No notifications')).not.toBeInTheDocument();
	});

	it('says "No notifications" when there really are none', async () => {
		stubFetch(() => ({ ok: true, status: 200, body: { notifications: [], unreadCount: 0 } }));
		await openBell();

		expect(await screen.findByText('No notifications')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
	});

	it('keeps the last notifications and marks them stale when a refresh fails', async () => {
		let ok = true;
		stubFetch(() => (ok
			? { ok: true, status: 200, body: { notifications: [NOTE], unreadCount: 1 } }
			: { ok: false, status: 502, body: {} }));
		// Reopening refetches only when the list is empty, so drive the 60 s poll instead
		vi.useFakeTimers({ shouldAdvanceTime: true });
		try {
			await openBell();
			expect(await screen.findByText('Port scan from 10.0.0.9')).toBeInTheDocument();

			ok = false;
			await vi.advanceTimersByTimeAsync(60_000);

			expect(await screen.findByText("Couldn't refresh notifications: showing the last ones.")).toBeInTheDocument();
			expect(screen.getByText('Port scan from 10.0.0.9')).toBeInTheDocument();
		} finally {
			vi.useRealTimers();
		}
	});
});
