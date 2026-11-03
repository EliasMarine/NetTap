import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import UpdatesPage from './+page.svelte';

const VERSIONS = {
	versions: {
		zeek: { name: 'Zeek', category: 'core', current_version: '6.0.4', install_type: 'docker', last_checked: '', status: 'ok', details: {} },
	},
	last_scan: '',
};

/** Answer each URL with its body (read at call time) and its code (200 by default), or HTTP 500 when it has none. */
function stubFetch(replies: Record<string, unknown>, codes: Record<string, number> = {}) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const body = replies[String(input)];
			if (body == null) return new Response('{}', { status: 500 });
			return new Response(JSON.stringify(body), { status: codes[String(input)] ?? 200 });
		}),
	);
}

describe('Software Updates page when a request fails (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('marks components Unknown, not "Up to Date", when the update list fails', async () => {
		stubFetch({ '/api/system/versions': VERSIONS });

		render(UpdatesPage);

		expect(await screen.findByText('Zeek')).toBeInTheDocument();
		expect(screen.getByText("Couldn't load the available updates: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('Unknown')).toBeInTheDocument();
		expect(screen.queryByText('Up to Date')).not.toBeInTheDocument();
	});

	it('says "Not checked", not "Up to Date", before the first update check since a restart', async () => {
		// the daemon's update list is empty until its first check; on the G11 that lasted minutes after a restart
		stubFetch({ '/api/system/versions': VERSIONS, '/api/system/updates/available': { updates: [], last_check: null } });

		render(UpdatesPage);

		expect(await screen.findByText('Zeek')).toBeInTheDocument();
		expect(screen.getByText('Updates have not been checked yet')).toBeInTheDocument();
		expect(screen.getByText('Not checked')).toBeInTheDocument();
		expect(screen.queryByText('Up to Date')).not.toBeInTheDocument();
	});

	it('says the installed versions failed instead of "No version information available"', async () => {
		stubFetch({ '/api/system/updates/available': { updates: [], last_check: '' } });

		render(UpdatesPage);

		expect(await screen.findByText("Couldn't load installed versions: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText(/No version information available/)).not.toBeInTheDocument();
	});

	it('says a failed "Check for Updates" failed instead of "checked just now"', async () => {
		stubFetch({ '/api/system/versions': VERSIONS, '/api/system/updates/available': { updates: [], last_check: '' } });

		render(UpdatesPage);
		await screen.findByText('Zeek');
		await fireEvent.click(screen.getByRole('button', { name: 'Check for Updates' }));

		expect(await screen.findByText("Couldn't check for updates: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('Last checked: Just now')).not.toBeInTheDocument();
	});

	it('says a failed update did not start instead of "Update Complete"', async () => {
		const update = {
			component: 'zeek', current_version: '6.0.4', latest_version: '6.0.5', update_type: 'patch',
			release_url: '', release_date: '', changelog: '', size_mb: 0, requires_restart: false,
		};
		stubFetch({ '/api/system/versions': VERSIONS, '/api/system/updates/available': { updates: [update], last_check: '' } });

		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update All' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 Component' }));

		expect(await screen.findByText("Couldn't start the update: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('Update Complete')).not.toBeInTheDocument();
	});

	it('names the sources the daemon could not check and marks their rows Unknown', async () => {
		const versions = {
			versions: {
				...VERSIONS.versions,
				'nettap-daemon': { name: 'nettap-daemon', category: 'core', current_version: '1.0.0', install_type: 'docker', last_checked: '', status: 'ok', details: {} },
			},
			last_scan: '',
		};
		stubFetch({
			'/api/system/versions': versions,
			// OLD CODE START — no check had run (last_check ''), which now reads "Not checked"
			// '/api/system/updates/available': { updates: [], last_check: '', failed_checks: ['nettap-daemon'] },
			// OLD CODE END
			// a check ran (last_check set): only then can an empty list read "Up to Date"
			'/api/system/updates/available': { updates: [], last_check: '2026-11-02T21:00:00Z', failed_checks: ['nettap-daemon'] },
		});

		render(UpdatesPage);

		expect(await screen.findByText("Couldn't check nettap-daemon for updates.")).toBeInTheDocument();
		// Zeek was checked and is current; the daemon's own release check failed
		expect(screen.getAllByText('Up to Date')).toHaveLength(1);
		expect(screen.getAllByText('Unknown')).toHaveLength(1);
	});

	// "component-versions" means the daemon couldn't read what's installed, so nothing was checked
	it('says no component could be checked when the installed versions could not be read', async () => {
		stubFetch({
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates: [], last_check: '', failed_checks: ['component-versions'] },
		});

		render(UpdatesPage);

		expect(
			await screen.findByText("Couldn't read the installed versions, so no component could be checked for updates."),
		).toBeInTheDocument();
		expect(screen.queryByText(/component-versions/)).not.toBeInTheDocument();
		expect(screen.queryByText('Up to Date')).not.toBeInTheDocument();
	});

	it('names container and docker checks the daemon could not make', async () => {
		const versions = {
			versions: {
				...VERSIONS.versions,
				grafana: { name: 'grafana', category: 'docker', current_version: '10.4.2', install_type: 'docker', last_checked: '', status: 'ok', details: {} },
			},
			last_scan: '',
		};
		stubFetch({
			'/api/system/versions': versions,
			'/api/system/updates/available': { updates: [], last_check: '', failed_checks: ['grafana', 'docker'] },
		});

		render(UpdatesPage);

		expect(await screen.findByText("Couldn't check grafana, docker for updates.")).toBeInTheDocument();
		expect(screen.getAllByText('Unknown')).toHaveLength(1);
	});

	it('shows the daemon\'s docker error row as an error', async () => {
		const versions = {
			versions: {
				docker: { name: 'docker', category: 'docker', current_version: 'unknown', install_type: 'docker', last_checked: '', status: 'error', details: {} },
			},
			last_scan: '',
		};
		stubFetch({ '/api/system/versions': versions, '/api/system/updates/available': { updates: [], last_check: '' } });

		render(UpdatesPage);

		expect(await screen.findByText('Error')).toBeInTheDocument();
		expect(screen.queryByText('Up to Date')).not.toBeInTheDocument();
	});

	it('still reads Up to Date when the update list loads and is empty', async () => {
		stubFetch({
			'/api/system/versions': VERSIONS,
			// OLD CODE START — no check had run (last_check ''), which now reads "Not checked"
			// '/api/system/updates/available': { updates: [], last_check: '' },
			// OLD CODE END
			'/api/system/updates/available': { updates: [], last_check: '2026-11-02T21:00:00Z' },
			'/api/system/updates/history': { history: [], count: 0 },
		});

		render(UpdatesPage);

		expect(await screen.findByText('Up to Date')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
	});
});

// The daemon now sends size_mb: null when nobody measured the update's size.
describe('Software Updates page — update size', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const update = (size_mb: number | null) => ({
		component: 'zeek', current_version: '6.0.4', latest_version: '6.0.5', update_type: 'patch',
		release_url: '', release_date: '', changelog: '', size_mb, requires_restart: false,
	});

	async function openUpdatePanel(size_mb: number | null) {
		stubFetch({
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates: [update(size_mb)], last_check: '' },
			'/api/system/updates/history': { history: [], count: 0 },
		});
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update All' }));
	}

	it('says the size is unknown when it was not measured', async () => {
		await openUpdatePanel(null);

		expect(await screen.findByText('size unknown')).toBeInTheDocument();
		expect(screen.queryByText(/null/)).not.toBeInTheDocument();
		expect(screen.queryByText(/0\.0 MB/)).not.toBeInTheDocument();
	});

	it('still shows a measured size', async () => {
		await openUpdatePanel(120);

		expect(await screen.findByText('120.0 MB')).toBeInTheDocument();
		expect(screen.queryByText('size unknown')).not.toBeInTheDocument();
	});
});

// The daemon replies {history, count}; the client treated that object as the list, so no history ever showed.
describe('Software Updates page — update history', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const PAST = {
		component: 'suricata', success: false, old_version: '7.0.2', new_version: '7.0.3',
		started_at: '2026-02-20T10:00:00Z', completed_at: '2026-02-20T10:01:30Z', error: 'pull failed', rollback_available: false,
	};

	it('shows past updates from the daemon reply', async () => {
		stubFetch({
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates: [], last_check: '' },
			'/api/system/updates/history': { history: [PAST], count: 1 },
		});

		render(UpdatesPage);

		expect(await screen.findByText('Update History')).toBeInTheDocument();
		expect(screen.getByText('1 past update')).toBeInTheDocument();
	});

	it('shows no history section and no error when there are no past updates', async () => {
		stubFetch({
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates: [], last_check: '' },
			'/api/system/updates/history': { history: [], count: 0 },
		});

		render(UpdatesPage);

		await screen.findByText('Zeek');
		expect(screen.queryByText('Update History')).not.toBeInTheDocument();
		expect(screen.queryByText(/update history/)).not.toBeInTheDocument();
	});

	it('says the history failed to load', async () => {
		stubFetch({ '/api/system/versions': VERSIONS, '/api/system/updates/available': { updates: [], last_check: '' } });

		render(UpdatesPage);

		expect(await screen.findByText("Couldn't load the update history: the request failed.")).toBeInTheDocument();
	});
});

// Malcolm's images are pinned: their updates come with a NetTap release, not from this page.
describe('Software Updates page — updates NetTap cannot apply', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const MALCOLM = "Comes with NetTap's pinned Malcolm release: update NetTap to get it.";
	const UPDATES = [
		{
			component: 'arkime', current_version: '26.02.0', latest_version: '26.03.0', update_type: 'minor',
			release_url: '', release_date: '', changelog: '', size_mb: null, requires_restart: true,
			applies_with: MALCOLM,
		},
		{
			component: 'suricata-rules', current_version: '2026-10-01', latest_version: '2026-11-02', update_type: 'patch',
			release_url: '', release_date: '', changelog: '', size_mb: null, requires_restart: true,
			applies_with: null,
		},
	];
	const versions = {
		versions: {
			arkime: { name: 'arkime', category: 'docker', current_version: '26.02.0', install_type: 'docker', last_checked: '', status: 'ok', details: {} },
			'suricata-rules': { name: 'suricata-rules', category: 'database', current_version: '2026-10-01', install_type: 'file', last_checked: '', status: 'ok', details: {} },
		},
		last_scan: '',
	};

	function stub() {
		stubFetch({
			'/api/system/versions': versions,
			'/api/system/updates/available': { updates: UPDATES, last_check: '' },
			'/api/system/updates/history': { history: [], count: 0 },
		});
	}

	it('leaves it out of Update All, disables its checkbox and says how it arrives', async () => {
		stub();
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update All' }));

		const pinned = screen.getByRole('checkbox', { name: /^arkime/ });
		expect(pinned).toBeDisabled();
		expect(pinned).not.toBeChecked();
		// OLD CODE START — the versions table now says it too
		// expect(screen.getByText(MALCOLM)).toBeInTheDocument();
		// OLD CODE END
		expect(within(pinned.closest('label')!).getByText(MALCOLM)).toBeInTheDocument();
		// the sentence replaces its size/restart detail; the rules row keeps both
		expect(screen.getAllByText('size unknown')).toHaveLength(1);
		expect(screen.getAllByText('Restart required')).toHaveLength(1);

		const rules = screen.getByRole('checkbox', { name: /^suricata-rules/ });
		expect(rules).toBeEnabled();
		expect(rules).toBeChecked();
		expect(screen.getByRole('button', { name: 'Update 1 Component' })).toBeEnabled();
	});

	it('offers no per-row Update button for it', async () => {
		stub();
		render(UpdatesPage);

		await screen.findByText('arkime');
		expect(await screen.findAllByRole('button', { name: 'Update' })).toHaveLength(1);
	});

	// On the G11 all 7 updates came with a NetTap release, yet the banner offered "Update All"
	it('offers no Update All when none of the updates can be applied here', async () => {
		stubFetch({
			'/api/system/versions': versions,
			'/api/system/updates/available': { updates: [UPDATES[0]], last_check: '' },
			'/api/system/updates/history': { history: [], count: 0 },
		});
		render(UpdatesPage);

		expect(await screen.findByText('1 update available')).toBeInTheDocument();
		expect(screen.getByText('None of these can be applied from here: each one says how it arrives.')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Update All' })).toBeNull();
		expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument();
	});
});

// On the G11 the page said "7 updates available" while every row read "Up to Date": the daemon
// sends versions as a list, so each row was keyed by its index and matched no update. Rows that
// nothing checks (the OS, Docker, Python) also read "Up to Date".
describe('Software Updates page — rows match the real reply', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows each row its own update, and "Not checked" for what the daemon does not check', async () => {
		const row = (name: string, category: string, current_version: string) =>
			({ name, category, current_version, install_type: 'docker', last_checked: '', status: 'ok', details: {} });
		stubFetch({
			'/api/system/versions': { versions: [row('logstash', 'docker', '26.02.0'), row('os', 'os', '12'), row('suricata-rules', 'database', '2026-11-02')], last_scan: '' },
			'/api/system/updates/available': {
				updates: [{ component: 'logstash', current_version: '26.02.0', latest_version: '26.10.0', update_type: 'minor', release_url: '', release_date: '',
					changelog: '', size_mb: null, requires_restart: true, applies_with: "Comes with NetTap's pinned Malcolm release: update NetTap to get it." }],
				last_check: '2026-11-02T21:00:00Z', failed_checks: [], checked: ['geoip-db', 'logstash', 'nettap-daemon', 'suricata-rules'],
			},
			'/api/system/updates/history': { history: [], count: 0 },
		});

		render(UpdatesPage);

		const status = async (name: string) => (await screen.findByText(name)).closest('.version-row')?.querySelector('.vtcol-status')?.textContent?.trim();
		expect(await status('logstash')).toBe('Update Available');
		expect(await status('os')).toBe('Not checked');
		expect(await status('suricata-rules')).toBe('Up to Date');
	});
});

// The daemon now starts an update in the background and answers at once (202); a Malcolm update
// runs 10–40 minutes, so the page follows it for as long as it runs.
describe('Software Updates page — a long-running update', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	const STATUS = '/api/system/updates/status';
	const ZEEK_UPDATE = {
		component: 'zeek', current_version: '6.0.4', latest_version: '6.0.5', update_type: 'patch',
		release_url: '', release_date: '', changelog: '', size_mb: null, requires_restart: false, applies_with: null,
	};
	const IDLE = {
		state: 'idle', components: [], current_component: null, current_step: null, progress_percent: 0,
		started_at: null, completed_at: null, results: [],
	};
	const running = (components: string[], current_step: string | null = null) => ({
		...IDLE, state: 'in_progress', components, current_component: components[0], current_step,
		progress_percent: 45, started_at: '2026-11-02T20:00:00Z',
	});
	const statusCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url) === STATUS).length;

	function stub(status: unknown, codes: Record<string, number> = {}) {
		const replies: Record<string, unknown> = {
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates: [ZEEK_UPDATE], last_check: '2026-11-02T21:00:00Z' },
			'/api/system/updates/history': { history: [], count: 0 },
			[STATUS]: status,
		};
		stubFetch(replies, codes);
		return replies;
	}

	it('calls a finished batch whose Malcolm update rolled back "Update Failed", with the reason', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const replies = stub(IDLE, { '/api/system/updates/apply': 202 });
		replies['/api/system/updates/apply'] = running(['zeek']);

		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update All' }));
		replies[STATUS] = {
			...running(['zeek']), state: 'completed', current_component: null, progress_percent: 100, completed_at: '2026-11-02T20:30:00Z',
			results: [{ component: 'zeek', success: false, old_version: '26.02.0', new_version: '26.02.0', started_at: '', completed_at: '',
				error: 'Not every container was running. NetTap rolled back to Malcolm 26.02.0.', rollback_available: false }],
		};
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 Component' }));
		await vi.advanceTimersByTimeAsync(3000);

		expect(await screen.findByText('Update Failed')).toBeInTheDocument();
		expect(screen.queryByText('Update Complete')).not.toBeInTheDocument();
		expect(screen.getByText(/NetTap rolled back to Malcolm 26.02.0/)).toBeInTheDocument();
	});

	it('keeps polling past 2 minutes while the update runs, and stops once it completes', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const replies = stub(IDLE, { '/api/system/updates/apply': 202 });
		replies['/api/system/updates/apply'] = running(['zeek']);

		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update All' }));
		replies[STATUS] = running(['zeek']);
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 Component' }));

		expect(await screen.findByText('45% complete')).toBeInTheDocument();
		await vi.advanceTimersByTimeAsync(150_000);
		expect(statusCalls()).toBeGreaterThanOrEqual(45);
		expect(screen.getByText('45% complete')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't confirm/)).not.toBeInTheDocument();

		replies[STATUS] = {
			...running(['zeek']), state: 'completed', current_component: null, progress_percent: 100, completed_at: '2026-11-02T20:03:00Z',
			results: [{ component: 'zeek', success: true, old_version: '6.0.4', new_version: '6.0.5', started_at: '', completed_at: '', error: null, rollback_available: false }],
		};
		await vi.advanceTimersByTimeAsync(3000);
		expect(await screen.findByText('Update Complete')).toBeInTheDocument();
		expect(screen.getByText('1 succeeded')).toBeInTheDocument();

		const callsWhenDone = statusCalls();
		await vi.advanceTimersByTimeAsync(30_000);
		expect(statusCalls()).toBe(callsWhenDone);
	});

	it('shows the current step under the progress bar', async () => {
		stub(running(['malcolm'], "Downloading Malcolm 26.10.0's images"));

		render(UpdatesPage);

		expect(await screen.findByText("Downloading Malcolm 26.10.0's images")).toBeInTheDocument();
	});

	it('follows an update already running when the page loads', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		stub(running(['malcolm']));

		render(UpdatesPage);

		expect(await screen.findByText('45% complete')).toBeInTheDocument();
		expect(screen.getByText('Updating...', { selector: '.card-title' })).toBeInTheDocument();
		expect(screen.getByText('malcolm', { selector: '.component-status-name' })).toBeInTheDocument();
		// in progress mode: nothing offers to start another update
		expect(screen.queryByRole('button', { name: /^Update \d+ Component/ })).toBeNull();

		const callsOnLoad = statusCalls();
		await vi.advanceTimersByTimeAsync(9000);
		expect(statusCalls()).toBeGreaterThanOrEqual(callsOnLoad + 3);
	});

	it('follows the running update when apply answers 409, without calling it a failure', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const replies = stub(IDLE, { '/api/system/updates/apply': 409 });
		replies['/api/system/updates/apply'] = { error: 'An update is already running', ...running(['malcolm'], 'Backing up OpenSearch') };

		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update All' }));
		replies[STATUS] = running(['malcolm'], 'Backing up OpenSearch');
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 Component' }));

		expect(await screen.findByText('Backing up OpenSearch')).toBeInTheDocument();
		expect(screen.getByText('malcolm', { selector: '.component-status-name' })).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't start the update/)).not.toBeInTheDocument();

		const callsAfter409 = statusCalls();
		await vi.advanceTimersByTimeAsync(3000);
		expect(statusCalls()).toBe(callsAfter409 + 1);
	});

	it('stops after 20 failed status reads in a row and says contact was lost', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const replies = stub(running(['malcolm']));

		render(UpdatesPage);
		expect(await screen.findByText('45% complete')).toBeInTheDocument();
		delete replies[STATUS];
		await vi.advanceTimersByTimeAsync(20 * 3000);

		expect(
			await screen.findByText('Lost contact with NetTap while the update was running: reload the page to see where it got to.'),
		).toBeInTheDocument();
		expect(screen.queryByText('Update Complete')).not.toBeInTheDocument();
		const callsWhenStopped = statusCalls();
		await vi.advanceTimersByTimeAsync(30_000);
		expect(statusCalls()).toBe(callsWhenStopped);
	});
});

// The versions table gains a "malcolm" row, which takes Malcolm's update; the image rows say they move with it.
describe('Software Updates page — the Malcolm row', () => {
	afterEach(() => vi.unstubAllGlobals());

	const MOVES_WITH = "Updates with the Malcolm row: Malcolm's images move together.";
	const row = (name: string, current_version: string) =>
		({ name, category: 'docker', current_version, install_type: 'docker', last_checked: '', status: 'ok', details: {} });
	const update = (component: string, current_version: string, latest_version: string, applies_with: string | null) => ({
		component, current_version, latest_version, update_type: 'minor', release_url: '', release_date: '', changelog: '',
		size_mb: null, requires_restart: true, applies_with,
	});

	function stub() {
		stubFetch({
			'/api/system/versions': { versions: [row('malcolm', '26.02.0'), row('arkime', '26.02.0')], last_scan: '' },
			'/api/system/updates/available': {
				updates: [update('malcolm', '26.02.0', '26.10.0', null), update('arkime', '26.02.0', '26.10.0', MOVES_WITH)],
				last_check: '2026-11-02T21:00:00Z',
			},
			'/api/system/updates/history': { history: [], count: 0 },
		});
	}
	const actionCell = async (name: string) =>
		(await screen.findByText(name, { selector: '.component-name' })).closest('.version-row')!.querySelector('.vtcol-action') as HTMLElement;

	it('shows the applies_with sentence in the action column, with no Update button for that row', async () => {
		stub();
		render(UpdatesPage);

		const cell = await actionCell('arkime');
		expect(within(cell).getByText(MOVES_WITH)).toBeInTheDocument();
		expect(within(cell).queryByRole('button')).toBeNull();
	});

	it('offers an Update button on the malcolm row', async () => {
		stub();
		render(UpdatesPage);

		const cell = await actionCell('malcolm');
		expect(within(cell).getByRole('button', { name: 'Update' })).toBeInTheDocument();
		expect(screen.getAllByRole('button', { name: 'Update' })).toHaveLength(1);
	});
});
