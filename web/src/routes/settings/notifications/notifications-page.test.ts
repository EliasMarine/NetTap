import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Page from './+page.svelte';

/** Stub fetch: URLs in `routes` get their body, everything else a 500. */
function stubFetch(routes: Record<string, unknown>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			const path = url.split('?')[0];
			if (!(path in routes)) return { ok: false, status: 500, json: async () => ({}) };
			return { ok: true, status: 200, json: async () => routes[path] };
		}),
	);
}

const CHANNEL = { id: 'ch1', type: 'discord', name: 'Home Discord', config: {} };

describe('Notification settings when requests fail (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says each section could not be loaded instead of "none configured"', async () => {
		stubFetch({});
		render(Page);

		expect(await screen.findByText("Couldn't load the notification channels: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the routing rules: the request failed.")).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the delivery log: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('Notification Channels (--)')).toBeInTheDocument();
		expect(screen.getByText('Routing Rules (--)')).toBeInTheDocument();
		expect(screen.queryByText(/No channels configured/)).not.toBeInTheDocument();
		expect(screen.queryByText('No routing rules configured.')).not.toBeInTheDocument();
		expect(screen.queryByText('No delivery attempts yet.')).not.toBeInTheDocument();
	});

	it('shows the real empty states when nothing is configured', async () => {
		stubFetch({
			'/api/notifications/channels': { channels: [], count: 0 },
			'/api/notifications/rules': { rules: [], count: 0 },
			'/api/notifications/log': { log: [], count: 0 },
		});
		render(Page);

		expect(await screen.findByText(/No channels configured/)).toBeInTheDocument();
		expect(screen.getByText('No routing rules configured.')).toBeInTheDocument();
		expect(screen.getByText('No delivery attempts yet.')).toBeInTheDocument();
		expect(screen.getByText('Notification Channels (0)')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
	});

	it('keeps the delivery log it had when the refresh after a test fails', async () => {
		const entry = { channel_id: 'ch1', channel_type: 'discord', title: 'Earlier alert', success: true, timestamp: '2026-11-01T10:00:00Z' };
		let logOk = true;
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url === '/api/notifications/channels') return { ok: true, status: 200, json: async () => ({ channels: [CHANNEL], count: 1 }) };
				if (url === '/api/notifications/rules') return { ok: true, status: 200, json: async () => ({ rules: [], count: 0 }) };
				if (url === '/api/notifications/log') {
					return logOk
						? { ok: true, status: 200, json: async () => ({ log: [entry], count: 1 }) }
						: { ok: false, status: 502, json: async () => ({}) };
				}
				if (url === '/api/notifications/channels/ch1/test') return { ok: true, status: 200, json: async () => ({ success: true }) };
				return { ok: false, status: 500, json: async () => ({}) };
			}),
		);
		render(Page);
		expect(await screen.findByText('Earlier alert')).toBeInTheDocument();

		logOk = false;
		await fireEvent.click(screen.getByRole('button', { name: 'Test' }));

		expect(await screen.findByText("Couldn't refresh the delivery log: showing the last entries.")).toBeInTheDocument();
		expect(screen.getByText('Earlier alert')).toBeInTheDocument();
	});
});
