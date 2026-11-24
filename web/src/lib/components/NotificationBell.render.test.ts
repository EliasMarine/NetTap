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

// NET-370 (QA 2026-11-23 #10): Escape left the popover open and aria-expanded true
describe('NotificationBell Escape (NET-370)', () => {
	const bell = () => screen.getByRole('button', { name: /^Notifications/ });
	const panelOpen = () => screen.queryByText('View all alerts') !== null;

	async function openWithUnread() {
		stubFetch(() => ({ ok: true, status: 200, body: { notifications: [NOTE], unreadCount: 1 } }));
		await openBell();
		return screen.findByRole('button', { name: 'Mark all read' });
	}

	function expectClosedOnBell() {
		expect(panelOpen()).toBe(false);
		expect(bell()).toHaveAttribute('aria-expanded', 'false');
		expect(bell()).toHaveFocus();
	}

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('closes from the bell and keeps focus there', async () => {
		await openWithUnread();
		expect(bell()).toHaveAttribute('aria-expanded', 'true');

		await fireEvent.keyDown(bell(), { key: 'Escape' });
		expectClosedOnBell();
	});

	it('closes from inside the panel, returns focus to the bell and marks nothing read', async () => {
		const markAll = await openWithUnread();
		markAll.focus();

		await fireEvent.keyDown(markAll, { key: 'Escape' });
		expectClosedOnBell();
		expect(fetch).not.toHaveBeenCalledWith('/api/notifications', expect.objectContaining({ method: 'POST' }));
	});

	it('closes after Mark all read removed the focused button', async () => {
		const markAll = await openWithUnread();
		markAll.focus();
		await fireEvent.click(markAll);
		await vi.waitFor(() => expect(screen.queryByRole('button', { name: 'Mark all read' })).not.toBeInTheDocument());
		expect(panelOpen()).toBe(true);
		expect(document.activeElement).toBe(document.body);

		await fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
		expectClosedOnBell();
	});

	it('keeps the Escape to itself, so an open alert detail stays open', async () => {
		const markAll = await openWithUnread();
		const onWindow = vi.fn();
		window.addEventListener('keydown', onWindow);
		try {
			await fireEvent.keyDown(markAll, { key: 'Escape' });
			expect(panelOpen()).toBe(false);
			expect(onWindow).not.toHaveBeenCalled();
		} finally {
			window.removeEventListener('keydown', onWindow);
		}
	});

	it("leaves Escape on a control outside the bell to that control", async () => {
		await openWithUnread();
		const outside = document.body.appendChild(document.createElement('input'));
		try {
			outside.focus();
			await fireEvent.keyDown(outside, { key: 'Escape' });
			expect(panelOpen()).toBe(true);
			expect(bell()).toHaveAttribute('aria-expanded', 'true');
			expect(outside).toHaveFocus();
		} finally {
			outside.remove();
		}
	});
});
