import { describe, it, expect, vi, afterEach } from 'vitest';
// OLD CODE: import { render, screen, fireEvent } from '@testing-library/svelte'; (NET-319: rows are checked with within)
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import type { JobState } from '$lib/api/notification-hub';
// OLD CODE: import Page from './+page.svelte'; (NET-273: the page is a Settings tab now)
import Page from './NotificationsTab.svelte';

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
		expect(screen.getByText("Couldn't load the background checks: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('— channels')).toBeInTheDocument();
		expect(screen.getByText('— rules')).toBeInTheDocument();
		expect(screen.getByText('— checks')).toBeInTheDocument();
		expect(screen.queryByText(/No channels configured/)).not.toBeInTheDocument();
		expect(screen.queryByText('No routing rules configured')).not.toBeInTheDocument();
		expect(screen.queryByText('No delivery attempts yet')).not.toBeInTheDocument();
	});

	it('shows the real empty states when nothing is configured', async () => {
		stubFetch({
			'/api/notifications/channels': { channels: [], count: 0 },
			'/api/notifications/rules': { rules: [], count: 0 },
			'/api/notifications/log': { log: [], count: 0 },
			'/api/jobs': { jobs: [] },
		});
		render(Page);

		expect(await screen.findByText(/No channels configured/)).toBeInTheDocument();
		expect(screen.getByText('No routing rules configured')).toBeInTheDocument();
		expect(screen.getByText('No delivery attempts yet')).toBeInTheDocument();
		expect(screen.getByText('No background checks')).toBeInTheDocument();
		expect(screen.getByText('0 channels')).toBeInTheDocument();
		expect(screen.getByText('0 checks')).toBeInTheDocument();
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
	// NET-273: the preferences card shares the tab, so its settings answer too (else its load-failed alert joins the page's)
	'/api/notifications/config': { min_severity: 2, email: { enabled: false, recipients: [], smtp_configured: true }, webhook: { enabled: false, has_url: false, url_hint: '' } },
	'/api/notifications/channels': { channels: [CHANNEL], count: 1 },
	'/api/notifications/rules': { rules: [], count: 0 },
	'/api/notifications/log': { log: [], count: 0 },
	// NET-319: the background checks load with the lists
	'/api/jobs': { jobs: [] },
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
		expect(screen.getByText('Loading background checks')).toBeInTheDocument();
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

	// OLD CODE: it('the rule form offers only the alert event, the one NetTap sends', …) expected ['alert'] (NET-319: new devices have a sender now)
	// OLD CODE: it('the rule form offers alerts and new devices, the events NetTap sends', …) (F6: and data cap warnings)
	// OLD CODE: it('the rule form offers alerts, new devices and data cap warnings, the events NetTap sends', …) (NET-331: and watched devices)
	it('the rule form offers alerts, new devices, data cap warnings and watched devices, the events NetTap sends', async () => {
		stubFetch(LISTS);
		render(Page);
		await screen.findByText('Home Discord');

		await fireEvent.click(screen.getByRole('button', { name: 'Add rule' }));

		const options = Array.from((screen.getByLabelText('Event type') as HTMLSelectElement).options).map((o) => o.value);
		// OLD CODE: expect(options).toEqual(['alert']);
		// OLD CODE: expect(options).toEqual(['new_device', 'alert']); (F6)
		// OLD CODE: expect(options).toEqual(['new_device', 'data_cap', 'alert']); (NET-331)
		expect(options).toEqual(['new_device', 'data_cap', 'watched_device', 'alert']);
		expect(screen.getByRole('option', { name: 'Data cap' })).toHaveValue('data_cap');
		expect(screen.getByRole('option', { name: 'Watched device' })).toHaveValue('watched_device');
		for (const unsent of ['anomaly', 'storage_warning', 'smart_warning', 'capture_error', 'system_error']) {
			expect(options).not.toContain(unsent);
		}
	});

	it('creates a new-device rule at All (4), the only minimum its medium events fire at, and hides the severity field', async () => {
		const fn = vi.fn(async (url: string, init?: RequestInit) => {
			if (url === '/api/notifications/rules' && init?.method === 'POST') {
				return { ok: true, status: 201, json: async () => ({ id: 'r1', ...JSON.parse(String(init.body)) }) };
			}
			const body = LISTS[url];
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 500, json: async () => ({}) };
		});
		vi.stubGlobal('fetch', fn);
		render(Page);
		await screen.findByText('Home Discord');

		await fireEvent.click(screen.getByRole('button', { name: 'Add rule' }));
		expect(screen.getByLabelText('Minimum severity')).toBeInTheDocument();
		await fireEvent.change(screen.getByLabelText('Event type'), { target: { value: 'new_device' } });
		expect(screen.queryByLabelText('Minimum severity')).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('checkbox', { name: /Home Discord/ }));
		await fireEvent.click(screen.getByRole('button', { name: 'Create rule' }));

		const post = fn.mock.calls.find(([url, init]) => url === '/api/notifications/rules' && init?.method === 'POST');
		expect(JSON.parse(String(post?.[1]?.body))).toEqual({ event_type: 'new_device', channels: ['ch1'], min_severity: 4 });
	});

	// F6 (NET-339): cap warnings are medium (80%, on track) or high (100%), so their rule takes All (4) too
	it('creates a data cap rule at All (4), with no severity field', async () => {
		const fn = vi.fn(async (url: string, init?: RequestInit) => {
			if (url === '/api/notifications/rules' && init?.method === 'POST') {
				return { ok: true, status: 201, json: async () => ({ id: 'r1', ...JSON.parse(String(init.body)) }) };
			}
			const body = LISTS[url];
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 500, json: async () => ({}) };
		});
		vi.stubGlobal('fetch', fn);
		render(Page);
		await screen.findByText('Home Discord');

		await fireEvent.click(screen.getByRole('button', { name: 'Add rule' }));
		await fireEvent.change(screen.getByLabelText('Event type'), { target: { value: 'data_cap' } });
		expect(screen.queryByLabelText('Minimum severity')).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('checkbox', { name: /Home Discord/ }));
		await fireEvent.click(screen.getByRole('button', { name: 'Create rule' }));

		const post = fn.mock.calls.find(([url, init]) => url === '/api/notifications/rules' && init?.method === 'POST');
		expect(JSON.parse(String(post?.[1]?.body))).toEqual({ event_type: 'data_cap', channels: ['ch1'], min_severity: 4 });
	});

	// NET-331: "Offline" is high (2) and "Back online" low (4), so a watched-device rule takes All (4) too
	it('creates a watched-device rule at All (4), with no severity field, and names it "Watched device"', async () => {
		const fn = vi.fn(async (url: string, init?: RequestInit) => {
			if (url === '/api/notifications/rules' && init?.method === 'POST') {
				return { ok: true, status: 201, json: async () => ({ id: 'r1', ...JSON.parse(String(init.body)) }) };
			}
			const body = LISTS[url];
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 500, json: async () => ({}) };
		});
		vi.stubGlobal('fetch', fn);
		render(Page);
		await screen.findByText('Home Discord');

		await fireEvent.click(screen.getByRole('button', { name: 'Add rule' }));
		await fireEvent.change(screen.getByLabelText('Event type'), { target: { value: 'watched_device' } });
		expect(screen.queryByLabelText('Minimum severity')).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('checkbox', { name: /Home Discord/ }));
		await fireEvent.click(screen.getByRole('button', { name: 'Create rule' }));

		const post = fn.mock.calls.find(([url, init]) => url === '/api/notifications/rules' && init?.method === 'POST');
		expect(JSON.parse(String(post?.[1]?.body))).toEqual({ event_type: 'watched_device', channels: ['ch1'], min_severity: 4 });
	});

	it('names a stored watched-device rule "Watched device"', async () => {
		stubFetch({
			...LISTS,
			'/api/notifications/rules': {
				rules: [{ id: 'settings-watched', event_type: 'watched_device', channels: ['ch1'], min_severity: 4, created_at: '2026-11-20T10:00:00Z' }],
				count: 1,
			},
		});
		render(Page);

		const row = (await screen.findByText('Watched device')).closest('li') as HTMLElement;
		expect(within(row).getByText(/to 1 channel/)).toBeInTheDocument();
	});

	it('names a stored data cap rule "Data cap"', async () => {
		stubFetch({
			...LISTS,
			'/api/notifications/rules': {
				rules: [{ id: 'settings-datacap', event_type: 'data_cap', channels: ['ch1'], min_severity: 4, created_at: '2026-11-18T10:00:00Z' }],
				count: 1,
			},
		});
		render(Page);

		const row = (await screen.findByText('Data cap')).closest('li') as HTMLElement;
		expect(within(row).getByText(/to 1 channel/)).toBeInTheDocument();
	});

	it('marks a rule that is off, and only that one (NET-319)', async () => {
		const rule = { channels: ['ch1'], min_severity: 4, created_at: '2026-11-18T10:00:00Z' };
		stubFetch({
			...LISTS,
			'/api/notifications/rules': {
				rules: [
					{ ...rule, id: 'settings-newdevice', event_type: 'new_device', enabled: false },
					{ ...rule, id: 'r-alert', event_type: 'alert' },
				],
				count: 2,
			},
		});
		render(Page);

		const offRow = (await screen.findByText('New device')).closest('li') as HTMLElement;
		const onRow = screen.getByText('Alert').closest('li') as HTMLElement;
		expect(within(offRow).getByText('Off')).toBeInTheDocument();
		expect(within(onRow).queryByText('Off')).not.toBeInTheDocument();
	});
});

// NET-319: the daemon's background checks, with Run now
describe('Notification settings background checks', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	function job(overrides: Partial<JobState> = {}): JobState {
		return {
			name: 'journal-compact',
			label: 'Event journal clean-up',
			every_s: 86_400,
			last_run: new Date(Date.now() - 2 * 3_600_000).toISOString(),
			last_duration_ms: 1234,
			last_error: null,
			partial: false,
			running: false,
			running_for_s: null,
			overdue: false,
			skipped_overlaps: 2,
			rss_mb_before: 80,
			rss_mb_after: 81,
			peak_rss_mb: 90,
			...overrides,
		};
	}

	/** LISTS, with `/api/jobs` answering from `jobsReplies` in turn and the run POST answering `run`. */
	function stubJobs(jobsReplies: JobState[][], run: { status: number; body: unknown } = { status: 202, body: {} }) {
		let reads = 0;
		const fn = vi.fn(async (url: string, init?: RequestInit) => {
			if (url === '/api/jobs/journal-compact/run' && init?.method === 'POST') {
				return { ok: run.status < 400, status: run.status, json: async () => run.body };
			}
			if (url === '/api/jobs') {
				const jobs = jobsReplies[Math.min(reads++, jobsReplies.length - 1)];
				return { ok: true, status: 200, json: async () => ({ jobs }) };
			}
			const body = LISTS[url];
			return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 500, json: async () => ({}) };
		});
		vi.stubGlobal('fetch', fn);
		return fn;
	}

	const table = () => screen.getByRole('table', { name: 'Background checks' });

	it('lists each check with when it last ran, how long it took and how it went', async () => {
		stubJobs([[job()]]);
		render(Page);

		const row = (await screen.findByText('Event journal clean-up')).closest('tr') as HTMLElement;
		expect(within(row).getByText('2h ago')).toBeInTheDocument();
		expect(within(row).getByText('1,234 ms')).toBeInTheDocument();
		expect(within(row).getByText('OK')).toBeInTheDocument();
		expect(within(row).getByText('2')).toBeInTheDocument();
		expect(screen.getByText('1 check')).toBeInTheDocument();
	});

	it('words each result: partial, the error, running, overdue and not run yet', async () => {
		stubJobs([
			[
				job({ name: 'a', label: 'Partial check', partial: true }),
				job({ name: 'b', label: 'Failing check', last_error: 'disk full' }),
				job({ name: 'c', label: 'Busy check', running: true, running_for_s: 5 }),
				job({ name: 'd', label: 'Stuck check', running: true, running_for_s: 300, overdue: true }),
				job({ name: 'e', label: 'New check', last_run: null, last_duration_ms: null }),
			],
		]);
		render(Page);

		const result = (label: string) => (screen.getByText(label).closest('tr') as HTMLElement);
		await screen.findByText('Partial check');
		expect(within(result('Partial check')).getByText('Partial')).toBeInTheDocument();
		expect(within(result('Failing check')).getByText('disk full')).toBeInTheDocument();
		expect(within(result('Busy check')).getByText('Running…')).toBeInTheDocument();
		expect(within(result('Stuck check')).getByText('Running, overdue')).toBeInTheDocument();
		expect(within(result('New check')).getByText('Not run yet')).toBeInTheDocument();
		expect(within(result('New check')).getByText('Never')).toBeInTheDocument();
		expect(within(result('New check')).getByText('—')).toBeInTheDocument();
		// a running check can't be started again
		// OLD CODE: { name: 'Run now' } (each row's button is named after its check now)
		expect(within(result('Busy check')).getByRole('button', { name: 'Run now: Busy check' })).toBeDisabled();
		expect(within(result('Partial check')).getByRole('button', { name: 'Run now: Partial check' })).toBeEnabled();
	});

	// OLD CODE START — only checked aria-sort, never the rows' order
	// it('sorts on every column, both ways', async () => {
	// 	stubJobs([[job(), job({ name: 'b', label: 'Another check', last_duration_ms: 5 })]]);
	// 	render(Page);
	// 	await screen.findByText('Another check');
	//
	// 	for (const label of ['Check', 'Last run', 'Took', 'Result', 'Skipped overlaps', 'Action']) {
	// 		const header = within(table()).getByRole('button', { name: label });
	// 		await fireEvent.click(header);
	// 		expect(header.closest('th')).toHaveAttribute('aria-sort', 'descending');
	// 		await fireEvent.click(header);
	// 		expect(header.closest('th')).toHaveAttribute('aria-sort', 'ascending');
	// 	}
	// });
	// OLD CODE END
	it('sorts on every column, both ways', async () => {
		// the slower check ran longer ago, so Took and Last run order the rows oppositely
		const older = job();
		const newer = job({ name: 'b', label: 'Another check', last_duration_ms: 5, last_run: new Date(Date.now() - 10 * 60_000).toISOString() });
		stubJobs([[older, newer]]);
		render(Page);
		await screen.findByText('Another check');
		const order = () => within(table()).getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[0].textContent?.trim());
		const expected: Record<string, [string[], string[]]> = {
			Took: [['Event journal clean-up', 'Another check'], ['Another check', 'Event journal clean-up']],
			'Last run': [['Another check', 'Event journal clean-up'], ['Event journal clean-up', 'Another check']],
		};

		for (const label of ['Check', 'Last run', 'Took', 'Result', 'Skipped overlaps', 'Action']) {
			const header = within(table()).getByRole('button', { name: label });
			await fireEvent.click(header);
			expect(header.closest('th')).toHaveAttribute('aria-sort', 'descending');
			if (expected[label]) expect(order()).toEqual(expected[label][0]);
			await fireEvent.click(header);
			expect(header.closest('th')).toHaveAttribute('aria-sort', 'ascending');
			if (expected[label]) expect(order()).toEqual(expected[label][1]);
		}
	});

	// OLD CODE START — a 202 only queues the run; the message said "started" and the list was read once
	// it('Run now starts the check, says so, and reloads the list', async () => {
	// 	const fn = stubJobs([[job()], [job({ running: true, running_for_s: 1 })]], {
	// 		status: 202,
	// 		body: { accepted: true, name: 'journal-compact' },
	// 	});
	// 	render(Page);
	// 	await screen.findByText('OK');
	//
	// 	await fireEvent.click(screen.getByRole('button', { name: 'Run now' }));
	//
	// 	expect(await screen.findByText('Running…')).toBeInTheDocument();
	// 	expect(screen.getByRole('status')).toHaveTextContent('"Event journal clean-up" started.');
	// 	expect(fn.mock.calls.filter(([url]) => url === '/api/jobs/journal-compact/run')).toHaveLength(1);
	// 	expect(fn.mock.calls.filter(([url]) => url === '/api/jobs')).toHaveLength(2);
	// });
	// OLD CODE END
	it('Run now asks for the check, says so, and keeps looking until the queued run starts', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		// the reload right after the 202 still shows it idle: the scheduler hasn't started it yet
		const fn = stubJobs([[job()], [job()], [job({ running: true, running_for_s: 1 })]], {
			status: 202,
			body: { accepted: true, name: 'journal-compact' },
		});
		render(Page);
		await screen.findByText('OK');

		await fireEvent.click(screen.getByRole('button', { name: 'Run now: Event journal clean-up' }));

		expect(await screen.findByRole('status')).toHaveTextContent(
			'Asked NetTap to run "Event journal clean-up". Its result shows under Background checks when it finishes.',
		);
		expect(fn.mock.calls.filter(([url]) => url === '/api/jobs/journal-compact/run')).toHaveLength(1);
		expect(fn.mock.calls.filter(([url]) => url === '/api/jobs')).toHaveLength(2);

		await vi.advanceTimersByTimeAsync(3_000);
		expect(await screen.findByText('Running…')).toBeInTheDocument();
		expect(fn.mock.calls.filter(([url]) => url === '/api/jobs')).toHaveLength(3);
	});

	it('reads a running check again every 3 s until it finishes, then stops', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const fn = stubJobs([[job({ running: true, running_for_s: 1 })], [job({ running: true, running_for_s: 4 })], [job()]]);
		const reads = () => fn.mock.calls.filter(([url]) => url === '/api/jobs').length;
		render(Page);
		await screen.findByText('Running…');
		expect(reads()).toBe(1);

		await vi.advanceTimersByTimeAsync(3_000);
		expect(reads()).toBe(2);
		expect(screen.getByText('Running…')).toBeInTheDocument();

		await vi.advanceTimersByTimeAsync(3_000);
		expect(await screen.findByText('OK')).toBeInTheDocument();
		expect(reads()).toBe(3);

		// finished: the polling stops
		await vi.advanceTimersByTimeAsync(30_000);
		expect(reads()).toBe(3);
	});

	// OLD CODE: one 409 test, with a made-up reason after a colon (the daemon's reasons are capitalised sentences)
	it.each([
		[409, 'That check is already running'],
		[404, 'No background check has that name'],
	])('Run now says why the daemon refused it (%i)', async (status, error) => {
		stubJobs([[job()]], { status, body: { error } });
		render(Page);
		await screen.findByText('OK');

		await fireEvent.click(screen.getByRole('button', { name: 'Run now: Event journal clean-up' }));

		expect(await screen.findByRole('alert')).toHaveTextContent(`Couldn't start "Event journal clean-up". ${error}.`);
	});

	it('keeps the last list when a refresh of the checks fails', async () => {
		let jobsOk = true;
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url === '/api/jobs') {
					return jobsOk
						? { ok: true, status: 200, json: async () => ({ jobs: [job()] }) }
						: { ok: false, status: 502, json: async () => ({}) };
				}
				const body = LISTS[url];
				return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 500, json: async () => ({}) };
			}),
		);
		render(Page);
		await screen.findByText('Event journal clean-up');

		jobsOk = false;
		expect(await refreshPage()).toBe('partial');

		expect(await screen.findByText("Couldn't refresh the background checks: showing the last list.")).toBeInTheDocument();
		expect(screen.getByText('Event journal clean-up')).toBeInTheDocument();
	});
});
