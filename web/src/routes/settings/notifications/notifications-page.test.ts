import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
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
		expect(screen.getByText('— channels')).toBeInTheDocument();
		expect(screen.getByText('— rules')).toBeInTheDocument();
		expect(screen.queryByText(/No channels configured/)).not.toBeInTheDocument();
		expect(screen.queryByText('No routing rules configured')).not.toBeInTheDocument();
		expect(screen.queryByText('No delivery attempts yet')).not.toBeInTheDocument();
	});

	it('shows the real empty states when nothing is configured', async () => {
		stubFetch({
			'/api/notifications/channels': { channels: [], count: 0 },
			'/api/notifications/rules': { rules: [], count: 0 },
			'/api/notifications/log': { log: [], count: 0 },
		});
		render(Page);

		expect(await screen.findByText(/No channels configured/)).toBeInTheDocument();
		expect(screen.getByText('No routing rules configured')).toBeInTheDocument();
		expect(screen.getByText('No delivery attempts yet')).toBeInTheDocument();
		expect(screen.getByText('0 channels')).toBeInTheDocument();
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

const LISTS: Record<string, unknown> = {
	'/api/notifications/channels': { channels: [CHANNEL], count: 1 },
	'/api/notifications/rules': { rules: [], count: 0 },
	'/api/notifications/log': { log: [], count: 0 },
};

describe('Notification settings card states', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows each card loading until the first load lands', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);

		expect(screen.getByText('Loading notification channels')).toBeInTheDocument();
		expect(screen.getByText('Loading routing rules')).toBeInTheDocument();
		expect(screen.getByText('Loading delivery log')).toBeInTheDocument();
	});

	it('offers a retry on a failed card that reloads the page', async () => {
		stubFetch({});
		render(Page);
		await screen.findByText("Couldn't load the notification channels: the request failed.");

		stubFetch(LISTS);
		await fireEvent.click(screen.getAllByRole('button', { name: 'Try again' })[0]);

		expect(await screen.findByText('Home Discord')).toBeInTheDocument();
		expect(screen.getByText('1 channel')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
	});
});

describe('Notification settings refresh contract (PLAN §5.5)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('registers its loader and reports ok, partial and failed', async () => {
		stubFetch(LISTS);
		render(Page);
		expect(get(pageRefresh).available).toBe(true);
		expect(await refreshPage()).toBe('ok');

		const { '/api/notifications/log': _log, ...withoutLog } = LISTS;
		stubFetch(withoutLog);
		expect(await refreshPage()).toBe('partial');

		stubFetch({});
		expect(await refreshPage()).toBe('failed');
	});

	it('writes nothing once the page has gone', async () => {
		let answer: () => void = () => {};
		const gate = new Promise<void>((resolve) => (answer = resolve));
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				await gate;
				return { ok: true, status: 200, json: async () => LISTS[url] };
			}),
		);
		const { unmount } = render(Page);
		const pending = refreshPage();
		unmount();
		answer();

		expect(await pending).toBe('skipped');
		expect(get(pageRefresh)).toMatchObject({ available: false, updatedAt: null });
	});
});

// NET-224: each channel shows how its last delivery went, and a failed test or save says why
describe('Notification settings delivery results', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function stubWithTest(channel: Record<string, unknown>, test: { status: number; body: unknown }) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url === '/api/notifications/channels/ch1/test') return { ok: test.status < 400, status: test.status, json: async () => test.body };
				const body = url === '/api/notifications/channels' ? { channels: [channel], count: 1 } : LISTS[url];
				return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 500, json: async () => ({}) };
			}),
		);
	}

	it("shows each channel's last delivery with the reason it failed", async () => {
		stubWithTest(
			{ ...CHANNEL, enabled: false, last_delivery: { ok: false, at: '2026-11-09T10:00:00Z', error: 'HTTP 404' } },
			{ status: 200, body: {} },
		);
		render(Page);

		expect(await screen.findByText(/^Failed .*: HTTP 404$/)).toBeInTheDocument();
		expect(screen.getByText('Off')).toBeInTheDocument();
	});

	it('a failed test says why', async () => {
		stubWithTest(CHANNEL, { status: 200, body: { success: false, channel_id: 'ch1', error: "can't connect to discord.example.net" } });
		render(Page);
		await screen.findByText('Home Discord');

		await fireEvent.click(screen.getByRole('button', { name: 'Test' }));

		expect(await screen.findByRole('alert')).toHaveTextContent("The test didn't go through: can't connect to discord.example.net.");
	});

	it('the rule form offers only the alert event, the one NetTap sends', async () => {
		stubFetch(LISTS);
		render(Page);
		await screen.findByText('Home Discord');

		await fireEvent.click(screen.getByRole('button', { name: 'Add rule' }));

		const options = Array.from((screen.getByLabelText('Event type') as HTMLSelectElement).options).map((o) => o.value);
		expect(options).toEqual(['alert']);
	});
});
