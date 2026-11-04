import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Page from './+page.svelte';
import { refreshPage } from '$lib/stores/pageRefresh';

const EVENT = {
	'@timestamp': '2026-11-02T08:00:00Z', event_type: 'device_joined',
	title: 'New device 10.0.0.42', description: '', metadata: {},
};

/** /api/changelog answers from `events()`; the event types always load. */
function stubFetch(events: () => { ok: boolean; status: number; body: unknown }) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) => {
			if (url === '/api/changelog/types') {
				return { ok: true, status: 200, json: async () => ({ event_types: ['device_joined', 'alert_triggered'] }) };
			}
			const r = events();
			return { ok: r.ok, status: r.status, json: async () => r.body };
		}),
	);
}

describe('Changelog page (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the events could not be loaded instead of "No events found"', async () => {
		stubFetch(() => ({ ok: false, status: 500, body: {} }));
		render(Page);

		expect(await screen.findByText("Couldn't load changelog events: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No events found for the selected filters.')).not.toBeInTheDocument();
	});

	it('says "No events found" when the filter really matches nothing', async () => {
		stubFetch(() => ({ ok: true, status: 200, body: { events: [], count: 0 } }));
		render(Page);

		expect(await screen.findByText('No events found for the selected filters.')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load/)).not.toBeInTheDocument();
	});

	it('says a failed filter change could not load, without showing the old filter\'s events', async () => {
		let ok = true;
		stubFetch(() => (ok
			? { ok: true, status: 200, body: { events: [EVENT], count: 1 } }
			: { ok: false, status: 502, body: {} }));
		render(Page);
		expect(await screen.findByText('New device 10.0.0.42')).toBeInTheDocument();

		ok = false;
		await fireEvent.change(screen.getByLabelText('Event type'), { target: { value: 'alert_triggered' } });

		expect(await screen.findByText("Couldn't load changelog events: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('New device 10.0.0.42')).not.toBeInTheDocument();
		expect(screen.queryByText('No events found for the selected filters.')).not.toBeInTheDocument();
	});
});

// PLAN §5.5: the page's loader is the top bar's Refresh, and an older load never wins.
describe('Changelog page — refresh contract', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the loading state while the events are on their way', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true');
		expect(screen.getByText('Loading changelog events')).toBeInTheDocument();
	});

	it('tells the top bar whether the refresh worked', async () => {
		let ok = true;
		stubFetch(() => (ok ? { ok: true, status: 200, body: { events: [EVENT], count: 1 } } : { ok: false, status: 500, body: {} }));
		render(Page);
		expect(await screen.findByText('New device 10.0.0.42')).toBeInTheDocument();
		expect(await refreshPage()).toBe('ok');
		ok = false;
		expect(await refreshPage()).toBe('failed');
		expect(screen.getByText("Couldn't load changelog events: the request failed.")).toBeInTheDocument();
	});

	it("drops an older filter's slower answer", async () => {
		const pending: Array<(body: unknown) => void> = [];
		vi.stubGlobal(
			'fetch',
			vi.fn((url: string) => {
				if (url === '/api/changelog/types') {
					return Promise.resolve({ ok: true, status: 200, json: async () => ({ event_types: ['device_joined', 'alert_triggered'] }) });
				}
				return new Promise((resolve) => pending.push((body) => resolve({ ok: true, status: 200, json: async () => body })));
			}),
		);
		render(Page);
		await vi.waitFor(() => expect(pending).toHaveLength(1));
		await fireEvent.change(screen.getByLabelText('Event type'), { target: { value: 'alert_triggered' } });
		await vi.waitFor(() => expect(pending).toHaveLength(2));

		pending[1]({ events: [{ ...EVENT, event_type: 'alert_triggered', title: 'Alert on 10.0.0.9' }], count: 1 });
		expect(await screen.findByText('Alert on 10.0.0.9')).toBeInTheDocument();
		pending[0]({ events: [EVENT], count: 1 });
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.queryByText('New device 10.0.0.42')).not.toBeInTheDocument();
		expect(screen.getByText('Alert on 10.0.0.9')).toBeInTheDocument();
	});
});
