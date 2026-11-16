import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import type { UpdateResult } from '$api/updates.js';
import UpdatesPage from './+page.svelte';

const VERSIONS = {
	versions: [
		{ name: 'Zeek', category: 'core', current_version: '6.0.4', install_type: 'docker', last_checked: '', status: 'ok', details: {} },
	],
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
		expect(screen.queryByText('Up to date')).not.toBeInTheDocument();
	});

	it('says "Not checked", not "Up to Date", before the first update check since a restart', async () => {
		// the daemon's update list is empty until its first check; on the G11 that lasted minutes after a restart
		stubFetch({ '/api/system/versions': VERSIONS, '/api/system/updates/available': { updates: [], last_check: null } });

		render(UpdatesPage);

		expect(await screen.findByText('Zeek')).toBeInTheDocument();
		expect(screen.getByText('Updates have not been checked yet')).toBeInTheDocument();
		expect(screen.getByText('Not checked')).toBeInTheDocument();
		expect(screen.queryByText('Up to date')).not.toBeInTheDocument();
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
		await fireEvent.click(screen.getByRole('button', { name: 'Check for updates' }));

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
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 component' }));

		// OLD CODE: expect(await screen.findByText("Couldn't start the update: the request failed.")).toBeInTheDocument(); (now with the status)
		expect(await screen.findByText("Couldn't start the update: the request failed (HTTP 500).")).toBeInTheDocument();
		expect(screen.queryByText('Update complete')).not.toBeInTheDocument();
	});

	it('names the sources the daemon could not check and marks their rows Unknown', async () => {
		const versions = {
			versions: [
				...VERSIONS.versions,
				{ name: 'nettap-daemon', category: 'core', current_version: '1.0.0', install_type: 'docker', last_checked: '', status: 'ok', details: {} },
			],
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
		expect(screen.getAllByText('Up to date')).toHaveLength(1);
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
		expect(screen.queryByText('Up to date')).not.toBeInTheDocument();
	});

	it('names container and docker checks the daemon could not make', async () => {
		const versions = {
			versions: [
				...VERSIONS.versions,
				{ name: 'grafana', category: 'docker', current_version: '10.4.2', install_type: 'docker', last_checked: '', status: 'ok', details: {} },
			],
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
			versions: [
				{ name: 'docker', category: 'docker', current_version: 'unknown', install_type: 'docker', last_checked: '', status: 'error', details: {} },
			],
			last_scan: '',
		};
		stubFetch({ '/api/system/versions': versions, '/api/system/updates/available': { updates: [], last_check: '' } });

		render(UpdatesPage);

		expect(await screen.findByText('Error')).toBeInTheDocument();
		expect(screen.queryByText('Up to date')).not.toBeInTheDocument();
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

		expect(await screen.findByText('Up to date')).toBeInTheDocument();
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
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
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

	// NET-166: the daemon's size_mb is decimal, so 1,000 MB is 1 GB (the 1024-based code read 1000.0 MB)
	it.each([
		[999.9, '999.9 MB'],
		[1000, '1.0 GB'],
		[2500, '2.5 GB'],
	])('shows %s MB as %s', async (sizeMb, text) => {
		await openUpdatePanel(sizeMb);

		expect(await screen.findByText(text)).toBeInTheDocument();
	});
});

// The daemon replies {history, count}; the client treated that object as the list, so no history ever showed.
describe('Software Updates page — update history', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	// OLD CODE START — a flat result; the daemon's history items are batches of results (batch() below)
	// const PAST = {
	// 	component: 'suricata', success: false, old_version: '7.0.2', new_version: '7.0.3',
	// 	started_at: '2026-02-20T10:00:00Z', completed_at: '2026-02-20T10:01:30Z', error: 'pull failed', rollback_available: false,
	// };
	// OLD CODE END
	const PAST = {
		component: 'suricata-rules', success: false, old_version: '2026-11-01', new_version: '2026-11-01',
		started_at: '2026-02-20T10:00:00Z', completed_at: '2026-02-20T10:01:30Z', error: 'pull failed', rollback_available: false,
	};
	const batch = (results: UpdateResult[], started_at = '2026-02-20T10:00:00Z') => ({
		results, components: results.map((r) => r.component), success: results.every((r) => r.success),
		total: results.length, succeeded: results.filter((r) => r.success).length, failed: results.filter((r) => !r.success).length,
		started_at, completed_at: '2026-02-20T10:01:30Z',
	});

	it('shows past updates from the daemon reply', async () => {
		stubFetch({
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates: [], last_check: '' },
			'/api/system/updates/history': { history: [batch([PAST])], count: 1 },
		});

		render(UpdatesPage);

		expect(await screen.findByText('Update history')).toBeInTheDocument();
		expect(screen.getByText('1 past update')).toBeInTheDocument();
	});

	// the rows read "undefined → undefined" with no component: each daemon item is a batch
	it('shows each result’s component, versions and error from a batch', async () => {
		const malcolm = { ...PAST, component: 'malcolm', success: true, old_version: '26.02.0', new_version: '26.10.0', error: null };
		stubFetch({
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates: [], last_check: '' },
			'/api/system/updates/history': { history: [batch([malcolm, PAST])], count: 1 },
		});

		render(UpdatesPage);

		const table = await screen.findByRole('table', { name: 'Update history' });
		expect(within(table).getByText('malcolm')).toBeInTheDocument();
		expect(within(table).getByText('26.02.0 → 26.10.0')).toBeInTheDocument();
		expect(within(table).getByText('pull failed')).toBeInTheDocument();
		expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
		// What's new lists the successful one
		expect(screen.getByText("What's new")).toBeInTheDocument();
	});

	it('renders two results for one component with no timestamps', async () => {
		const bare = { ...PAST, component: 'malcolm', started_at: '', completed_at: '' };
		stubFetch({
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates: [], last_check: '' },
			'/api/system/updates/history': { history: [{ ...batch([bare, bare]), started_at: '', completed_at: '' }], count: 1 },
		});

		render(UpdatesPage);

		const table = await screen.findByRole('table', { name: 'Update history' });
		expect(within(table).getAllByText('malcolm')).toHaveLength(2);
	});

	it('shows no history section and no error when there are no past updates', async () => {
		stubFetch({
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates: [], last_check: '' },
			'/api/system/updates/history': { history: [], count: 0 },
		});

		render(UpdatesPage);

		await screen.findByText('Zeek');
		expect(screen.queryByText('Update history')).not.toBeInTheDocument();
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
		versions: [
			{ name: 'arkime', category: 'docker', current_version: '26.02.0', install_type: 'docker', last_checked: '', status: 'ok', details: {} },
			{ name: 'suricata-rules', category: 'database', current_version: '2026-10-01', install_type: 'file', last_checked: '', status: 'ok', details: {} },
		],
		last_scan: '',
	};

	function stub() {
		stubFetch({
			'/api/system/versions': versions,
			'/api/system/updates/available': { updates: UPDATES, last_check: '' },
			'/api/system/updates/history': { history: [], count: 0 },
		});
	}

	// OLD CODE: it('leaves it out of Update All, disables its checkbox and says how it arrives', … (NET-311: a disabled checkbox looked live)
	it('lists it apart from the picks, with no checkbox, and says how it arrives', async () => {
		stub();
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));

		// OLD CODE START — it had a disabled checkbox, which looked like a live one
		// const pinned = screen.getByRole('checkbox', { name: /^arkime/ });
		// expect(pinned).toBeDisabled();
		// expect(pinned).not.toBeChecked();
		// // OLD CODE START — the versions table now says it too
		// // expect(screen.getByText(MALCOLM)).toBeInTheDocument();
		// // OLD CODE END
		// expect(within(pinned.closest('label')!).getByText(MALCOLM)).toBeInTheDocument();
		// OLD CODE END
		expect(screen.queryByRole('checkbox', { name: /^arkime/ })).toBeNull();
		expect(screen.getByText("Can't be updated from here")).toBeInTheDocument();
		const other = screen.getByText('arkime', { selector: '.other-list b' }).closest('li')!;
		expect(within(other).getByText(MALCOLM)).toBeInTheDocument();
		// the sentence replaces its size/restart detail; the rules row keeps both
		expect(screen.getAllByText('size unknown')).toHaveLength(1);
		expect(screen.getAllByText('Restart required')).toHaveLength(1);

		const rules = screen.getByRole('checkbox', { name: /^suricata-rules/ });
		expect(rules).toBeEnabled();
		expect(rules).toBeChecked();
		expect(screen.getAllByRole('checkbox')).toHaveLength(1);
		expect(screen.getByRole('button', { name: 'Update 1 component' })).toBeEnabled();
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
		expect(screen.queryByRole('button', { name: 'Update all' })).toBeNull();
		// OLD CODE: expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument(); (it opened a picker with nothing to pick, NET-311)
		expect(screen.queryByRole('button', { name: 'Review' })).toBeNull();
	});
});

// NET-311: on the G11 nothing listed could be applied, yet Review opened "Apply updates" with two
// disabled (live-looking) checkboxes and "Update 0 components"
describe('Software Updates page — the Apply updates picker (NET-311)', () => {
	afterEach(() => vi.unstubAllGlobals());

	const APPLY = '/api/system/updates/apply';
	const upd = (component: string, extra: Record<string, unknown> = {}) => ({
		component, current_version: '1', latest_version: '2', update_type: 'patch', release_url: '', release_date: '',
		changelog: '', size_mb: null, requires_restart: false, applies_with: null, ...extra,
	});
	// the G11's reply of 2026-11-16
	const GEOIP_WITH = "Comes with Malcolm's Logstash image: a newer one arrives with a newer Malcolm release.";
	const OS_WITH = 'Install them on the box itself: run sudo apt update, then sudo apt upgrade.';
	const GEOIP = upd('geoip-db', {
		current_version: '2026-09-29', latest_version: 'newer weekly release', changelog: "Logstash's GeoIP database is 47 day(s) old",
		applies_with: GEOIP_WITH,
	});
	const OS = upd('os', {
		current_version: '24.04', latest_version: '1 package update', update_type: 'unknown',
		changelog: '1 Ubuntu package update is ready to install, 0 of them security updates (as of 2026-11-16 08:39 UTC).',
		applies_with: OS_WITH,
	});
	const RULES = upd('suricata-rules', { current_version: '2026-11-01', latest_version: '2026-11-16', changelog: 'Suricata rules are 12 day(s) old' });
	const MALCOLM_NOTES = '## Malcolm 26.10.0\n- Zeek 7.1\n- Suricata 7.0.8';
	const MALCOLM = upd('malcolm', {
		current_version: '26.02.0', latest_version: '26.10.0', update_type: 'unknown', changelog: MALCOLM_NOTES, requires_restart: true,
	});
	const status = (state: string, components: string[]) => ({
		state, components, current_component: state === 'in_progress' ? components[0] : null, current_step: null,
		progress_percent: state === 'in_progress' ? 45 : 100, started_at: '2026-11-16T17:20:00Z', completed_at: null, results: [],
	});

	function stub(updates: unknown[]) {
		const replies: Record<string, unknown> = {
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates, last_check: '2026-11-16T17:17:32Z' },
			'/api/system/updates/history': { history: [], count: 0 },
			[APPLY]: status('completed', []),
		};
		stubFetch(replies, { [APPLY]: 202 });
		return replies;
	}
	const applied = () =>
		vi.mocked(fetch).mock.calls
			.filter(([url]) => String(url) === APPLY)
			.map(([, init]) => JSON.parse(String(init?.body)).components);

	it("shows the G11's updates as information, with no picker, when none can be applied here", async () => {
		stub([GEOIP, OS]);
		render(UpdatesPage);

		const banner = (await screen.findByText('2 updates available')).closest('article')!;
		expect(screen.queryByRole('button', { name: 'Review' })).toBeNull();
		expect(screen.queryByRole('button', { name: 'Update all' })).toBeNull();
		expect(screen.queryByRole('checkbox')).toBeNull();
		expect(screen.queryByText('Apply updates')).toBeNull();
		for (const u of [GEOIP, OS]) {
			expect(within(banner).getByText(u.component)).toBeInTheDocument();
			expect(within(banner).getByText(String(u.changelog))).toBeInTheDocument();
			expect(within(banner).getByText(String(u.applies_with))).toBeInTheDocument();
		}
		expect(within(banner).queryByText('unknown')).toBeNull();
		expect(within(banner).queryByRole('button', { name: /^Changelog/ })).toBeNull();
	});

	it('ticks and unticks each pick, counts only the ticked ones and sends them', async () => {
		stub([RULES, MALCOLM]);
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));

		const rules = screen.getByRole('checkbox', { name: /^suricata-rules/ });
		const malcolm = screen.getByRole('checkbox', { name: /^malcolm/ });
		expect(rules).toBeChecked();
		expect(malcolm).toBeChecked();
		expect(screen.getByRole('button', { name: 'Update 2 components' })).toBeEnabled();

		await fireEvent.click(rules);
		expect(rules).not.toBeChecked();
		expect(screen.getByRole('button', { name: 'Update 1 component' })).toBeEnabled();
		await fireEvent.click(rules);
		expect(rules).toBeChecked();
		expect(screen.getByRole('button', { name: 'Update 2 components' })).toBeEnabled();
		await fireEvent.click(rules);
		await fireEvent.click(malcolm);
		expect(screen.getByRole('button', { name: 'Update 0 components' })).toBeDisabled();
		// the update type "unknown" isn't printed
		expect(screen.queryByText('unknown')).toBeNull();

		await fireEvent.click(malcolm);
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 component' }));
		await screen.findByText('Update complete');
		expect(applied()).toEqual([['malcolm']]);
	});

	it('closes the picker when a refresh leaves nothing to apply', async () => {
		const replies = stub([RULES, GEOIP]);
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
		expect(screen.getByRole('checkbox', { name: /^suricata-rules/ })).toBeChecked();

		replies['/api/system/updates/available'] = { updates: [GEOIP], last_check: '2026-11-16T17:30:00Z' };
		await refreshPage();

		expect(await screen.findByText('1 update available')).toBeInTheDocument();
		expect(screen.queryByText('Apply updates')).toBeNull();
		expect(screen.queryByRole('checkbox')).toBeNull();
		expect(screen.queryByRole('button', { name: 'Review' })).toBeNull();
		expect(screen.getAllByText(GEOIP_WITH).length).toBeGreaterThan(0);
	});

	it("doesn't reopen the picker unasked when a later refresh brings an update back", async () => {
		const replies = stub([RULES, GEOIP]);
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
		replies['/api/system/updates/available'] = { updates: [GEOIP], last_check: '2026-11-16T17:30:00Z' };
		await refreshPage();
		expect(await screen.findByText('1 update available')).toBeInTheDocument();

		replies['/api/system/updates/available'] = { updates: [RULES, GEOIP], last_check: '2026-11-16T17:40:00Z' };
		await refreshPage();

		expect(await screen.findByText('2 updates available')).toBeInTheDocument();
		expect(screen.queryByText('Apply updates')).toBeNull();
		expect(screen.queryByRole('checkbox')).toBeNull();
		// opening it again starts from a fresh pick
		await fireEvent.click(screen.getByRole('button', { name: 'Review' }));
		expect(screen.getByRole('checkbox', { name: /^suricata-rules/ })).toBeChecked();
		expect(screen.getByRole('button', { name: 'Update 1 component' })).toBeEnabled();
	});

	it('puts a NetTap release’s multi-line notes in the accordion, in the banner and under the picks', async () => {
		const NOTES = '## NetTap v0.4.0-alpha.3\n- Apply updates lists what it can update\n- Fixes';
		const NETTAP = upd('nettap-daemon', {
			current_version: '0.4.0-alpha.2', latest_version: 'v0.4.0-alpha.3', changelog: NOTES,
			applies_with: 'Comes with a NetTap release: update NetTap to get it.',
		});
		const replies = stub([NETTAP]);
		const { unmount } = render(UpdatesPage);

		const notesIn = (scope: HTMLElement) => {
			const item = within(scope).getByText('nettap-daemon', { selector: '.other-list b' }).closest('li')!;
			expect(within(item).getByRole('button', { name: /^Changelog/ })).toBeInTheDocument();
			expect(item.querySelector('pre.changelog')?.textContent).toBe(NOTES);
			// no raw blob beside it
			expect([...item.querySelectorAll('span.dim')].some((s) => s.textContent?.includes('Fixes'))).toBe(false);
		};
		notesIn((await screen.findByText('1 update available')).closest('article')!);
		unmount();

		replies['/api/system/updates/available'] = { updates: [RULES, NETTAP], last_check: '2026-11-16T17:17:32Z' };
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
		notesIn(screen.getByText('Apply updates').closest('article')!);
	});

	it('counts and sends only the picks still listed after a refresh', async () => {
		const replies = stub([RULES, MALCOLM]);
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
		expect(screen.getByRole('button', { name: 'Update 2 components' })).toBeEnabled();

		replies['/api/system/updates/available'] = { updates: [MALCOLM], last_check: '2026-11-16T17:30:00Z' };
		await refreshPage();

		await fireEvent.click(await screen.findByRole('button', { name: 'Update 1 component' }));
		await screen.findByText('Update complete');
		expect(applied()).toEqual([['malcolm']]);
	});

	it('shows a one-line changelog inline and keeps the accordion for release notes', async () => {
		stub([RULES, MALCOLM]);
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));

		const rulesLabel = screen.getByRole('checkbox', { name: /^suricata-rules/ }).closest('label')!;
		expect(within(rulesLabel).getByText('Suricata rules are 12 day(s) old')).toBeInTheDocument();
		expect(within(rulesLabel.closest('li')!).queryByRole('button', { name: /^Changelog/ })).toBeNull();

		const malcolmItem = screen.getByRole('checkbox', { name: /^malcolm/ }).closest('li')!;
		expect(within(malcolmItem).getByRole('button', { name: /^Changelog/ })).toBeInTheDocument();
		expect(malcolmItem.querySelector('label')!.textContent).not.toContain('Zeek 7.1');
		expect(screen.getAllByRole('button', { name: /^Changelog/ })).toHaveLength(1);
	});

	it.each([
		[159, 'inline'],
		[160, 'accordion'],
	])('shows a %s-character one-line changelog %s', async (length, where) => {
		const text = 'x'.repeat(length);
		stub([{ ...RULES, changelog: text }]);
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));

		const label = screen.getByRole('checkbox', { name: /^suricata-rules/ }).closest('label')!;
		const accordion = screen.queryByRole('button', { name: /^Changelog/ });
		if (where === 'inline') {
			expect(within(label).getByText(text)).toBeInTheDocument();
			expect(accordion).toBeNull();
		} else {
			expect(within(label).queryByText(text)).toBeNull();
			expect(accordion).toBeInTheDocument();
		}
	});

	it('keeps the picks fixed while the start request is pending, also through a refresh', async () => {
		const replies = stub([RULES, GEOIP]);
		let answer!: (r: Response) => void;
		const stubbed = vi.mocked(fetch).getMockImplementation()!;
		vi.mocked(fetch).mockImplementation((input, init) =>
			String(input) === APPLY ? new Promise<Response>((resolve) => (answer = resolve)) : stubbed(input, init),
		);
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 component' }));

		expect(await screen.findByText('Starting the update…')).toBeInTheDocument();
		expect(screen.queryByRole('checkbox')).toBeNull();

		replies['/api/system/updates/available'] = { updates: [GEOIP], last_check: '2026-11-16T17:30:00Z' };
		await refreshPage();
		expect(screen.getByText('Starting the update…')).toBeInTheDocument();
		expect(screen.queryByRole('checkbox')).toBeNull();
		expect(screen.queryByText('Select the components you want to update:')).toBeNull();
		expect(screen.queryByRole('button', { name: 'Review' })).toBeNull();

		answer(new Response(JSON.stringify(status('in_progress', ['suricata-rules'])), { status: 202 }));
		expect(await screen.findByText('45% complete')).toBeInTheDocument();
		expect(screen.getByText('suricata-rules', { selector: '.component-status-name' })).toBeInTheDocument();
		expect(screen.queryByText('Starting the update…')).toBeNull();
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

		// OLD CODE: const status = async (name: string) => (await screen.findByText(name)).closest('tr')?.querySelector('.vtcol-status')?.textContent?.trim(); (the banner now lists logstash too)
		const status = async (name: string) =>
			(await screen.findByText(name, { selector: '.component-name' })).closest('tr')?.querySelector('.vtcol-status')?.textContent?.trim();
		expect(await status('logstash')).toBe('Update available');
		expect(await status('os')).toBe('Not checked');
		expect(await status('suricata-rules')).toBe('Up to date');
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
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
		replies[STATUS] = {
			...running(['zeek']), state: 'completed', current_component: null, progress_percent: 100, completed_at: '2026-11-02T20:30:00Z',
			results: [{ component: 'zeek', success: false, old_version: '26.02.0', new_version: '26.02.0', started_at: '', completed_at: '',
				error: 'Not every container was running. NetTap rolled back to Malcolm 26.02.0.', rollback_available: false }],
		};
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 component' }));
		await vi.advanceTimersByTimeAsync(3000);

		expect(await screen.findByText('Update failed')).toBeInTheDocument();
		expect(screen.queryByText('Update complete')).not.toBeInTheDocument();
		expect(screen.getByText(/NetTap rolled back to Malcolm 26.02.0/)).toBeInTheDocument();
	});

	it('keeps polling past 2 minutes while the update runs, and stops once it completes', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const replies = stub(IDLE, { '/api/system/updates/apply': 202 });
		replies['/api/system/updates/apply'] = running(['zeek']);

		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
		replies[STATUS] = running(['zeek']);
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 component' }));

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
		expect(await screen.findByText('Update complete')).toBeInTheDocument();
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
		expect(screen.getByText('Updating…', { selector: '.card-title' })).toBeInTheDocument();
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
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
		replies[STATUS] = running(['malcolm'], 'Backing up OpenSearch');
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 component' }));

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
		expect(screen.queryByText('Update complete')).not.toBeInTheDocument();
		const callsWhenStopped = statusCalls();
		await vi.advanceTimersByTimeAsync(30_000);
		expect(statusCalls()).toBe(callsWhenStopped);
	});

	// Batch A finished and another tab started B between two polls: B's progress isn't A's
	const B_STARTED = '2026-11-02T20:20:00Z';
	const finishedA = {
		results: [{ component: 'zeek', success: true, old_version: '6.0.4', new_version: '6.0.5', started_at: '', completed_at: '', error: null, rollback_available: false }],
		components: ['zeek'], success: true, total: 1, succeeded: 1, failed: 0,
		started_at: '2026-11-02T20:00:00Z', completed_at: '2026-11-02T20:10:00Z',
	};

	it("shows the followed update's result from the history when another one is running", async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const replies = stub(running(['zeek']));

		render(UpdatesPage);
		expect(await screen.findByText('45% complete')).toBeInTheDocument();
		replies[STATUS] = { ...running(['malcolm'], 'Backing up OpenSearch'), progress_percent: 70, started_at: B_STARTED };
		replies['/api/system/updates/history'] = { history: [finishedA], count: 1 };
		await vi.advanceTimersByTimeAsync(3000);

		expect(await screen.findByText('Update complete')).toBeInTheDocument();
		expect(screen.getByText('1 succeeded')).toBeInTheDocument();
		expect(screen.queryByText('70% complete')).not.toBeInTheDocument();
		expect(screen.queryByText('Backing up OpenSearch')).not.toBeInTheDocument();
		const callsWhenSettled = statusCalls();
		await vi.advanceTimersByTimeAsync(9000);
		expect(statusCalls()).toBe(callsWhenSettled); // it doesn't adopt B
	});

	it('says the outcome is not confirmed when the history lacks the followed update', async () => {
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const replies = stub(running(['zeek']));

		render(UpdatesPage);
		expect(await screen.findByText('45% complete')).toBeInTheDocument();
		// after a restart: an older batch is the daemon's last, and the followed one was never recorded
		replies[STATUS] = { ...IDLE, state: 'completed', progress_percent: 100, started_at: '2026-11-01T08:00:00Z', results: finishedA.results };
		await vi.advanceTimersByTimeAsync(3000);

		expect(await screen.findByText(/NetTap lost track of it, for example after a restart/)).toBeInTheDocument();
		expect(screen.getByText('Update not confirmed', { selector: '.card-title' })).toBeInTheDocument();
		expect(screen.queryByText('Update complete')).not.toBeInTheDocument();
	});

	it("shows the daemon's reason when it refuses to start an update", async () => {
		const replies = stub(IDLE, { '/api/system/updates/apply': 400 });
		replies['/api/system/updates/apply'] = { error: 'components must be names NetTap can update' };

		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Update all' }));
		await fireEvent.click(screen.getByRole('button', { name: 'Update 1 component' }));

		expect(await screen.findByText("Couldn't start the update: components must be names NetTap can update")).toBeInTheDocument();
	});

	it('only mentions Malcolm in the progress note when Malcolm is updating', async () => {
		stub(running(['suricata-rules'], 'Updating the Suricata rules'));
		render(UpdatesPage);
		expect(await screen.findByText('You can leave this page and come back')).toBeInTheDocument();
		expect(screen.queryByText(/A Malcolm update takes/)).not.toBeInTheDocument();
	});
});

// The daemon reports when its update list is older than 6 hours, or empty since a restart
describe('Software Updates page — checks on its own when the list is stale', () => {
	afterEach(() => vi.unstubAllGlobals());

	const checkCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url) === '/api/system/updates/check').length;

	it.each([
		[true, 1],
		[false, 0],
		[undefined, 0],
	])('stale: %s runs %i check(s)', async (stale, checks) => {
		stubFetch({
			'/api/system/versions': VERSIONS,
			'/api/system/updates/available': { updates: [], last_check: stale ? null : '2026-11-02T21:00:00Z', stale },
			'/api/system/updates/history': { history: [], count: 0 },
			'/api/system/updates/check': { updates: [], last_check: '2026-11-16T07:00:00Z', failed_checks: [], checked: ['Zeek'] },
		});

		render(UpdatesPage);
		await screen.findByText('Zeek');
		await vi.waitFor(() => expect(checkCalls()).toBe(checks));
		if (checks) expect(await screen.findByText('Up to date')).toBeInTheDocument();
	});
});

// The client read a {result} the daemon never sends, so its reason never reached the page
describe('Software Updates page — rolling back', () => {
	afterEach(() => vi.unstubAllGlobals());

	const RULES = {
		component: 'suricata-rules', success: true, old_version: '2026-11-01', new_version: '2026-11-02',
		started_at: '2026-11-02T20:00:00Z', completed_at: '2026-11-02T20:01:00Z', error: null, rollback_available: true,
	};

	async function rollBack(reply: unknown, code: number) {
		stubFetch(
			{
				'/api/system/versions': VERSIONS,
				'/api/system/updates/available': { updates: [], last_check: '2026-11-02T21:00:00Z' },
				'/api/system/updates/history': {
					history: [{ results: [RULES], components: ['suricata-rules'], success: true, started_at: RULES.started_at, completed_at: RULES.completed_at }],
					count: 1,
				},
				'/api/system/updates/rollback': reply,
			},
			{ '/api/system/updates/rollback': code },
		);
		render(UpdatesPage);
		await fireEvent.click(await screen.findByRole('button', { name: 'Roll back' }));
	}

	it('says what the rollback did', async () => {
		await rollBack({ success: true, component: 'suricata-rules', message: 'Restored the rules from backup 20261102' }, 200);
		expect(await screen.findByText('Restored the rules from backup 20261102')).toBeInTheDocument();
	});

	it("shows the daemon's reason when there is nothing to restore", async () => {
		await rollBack({ success: false, component: 'suricata-rules', message: 'No backup available for component: suricata-rules' }, 404);
		expect(await screen.findByText("Couldn't roll back suricata-rules: No backup available for component: suricata-rules")).toBeInTheDocument();
	});

	it('shows the proxy’s reason when the daemon is down', async () => {
		await rollBack({ error: 'Daemon unreachable', daemonAvailable: false }, 502);
		expect(await screen.findByText("Couldn't roll back suricata-rules: Daemon unreachable")).toBeInTheDocument();
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
		(await screen.findByText(name, { selector: '.component-name' })).closest('tr')!.querySelector('.vtcol-action') as HTMLElement;

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

// ---------------------------------------------------------------------------
// Redesign: card states, table sorting and the page refresh contract (PLAN.md §5.5)
// ---------------------------------------------------------------------------

const ANSWERED: Record<string, unknown> = {
	'/api/system/versions': VERSIONS,
	'/api/system/updates/available': { updates: [], last_check: '2026-11-02T21:00:00Z' },
	'/api/system/updates/history': { history: [], count: 0 },
	'/api/system/updates/status': {
		state: 'idle', components: [], current_component: null, current_step: null, progress_percent: 0,
		started_at: null, completed_at: null, results: [],
	},
};

describe('Software Updates page — card states', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows the versions card loading while the request is pending', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})));

		render(UpdatesPage);

		expect(screen.getByText('Loading version information').closest('[role="status"]')).toHaveAttribute('aria-busy', 'true');
	});

	it('offers Try again on a failed versions load, which loads again', async () => {
		stubFetch({ '/api/system/updates/available': { updates: [], last_check: '' } });
		const versionCalls = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url) === '/api/system/versions').length;

		render(UpdatesPage);

		const error = (await screen.findByText("Couldn't load installed versions: the request failed.")).closest('[role="alert"]') as HTMLElement;
		const before = versionCalls();
		await fireEvent.click(within(error).getByRole('button', { name: 'Try again' }));
		await vi.waitFor(() => expect(versionCalls()).toBe(before + 1));
	});

	it('shows the empty state when the daemon lists no components', async () => {
		stubFetch({ ...ANSWERED, '/api/system/versions': { versions: [], last_scan: '' } });

		render(UpdatesPage);

		expect(await screen.findByText('No version information available')).toBeInTheDocument();
	});

	it('keeps the rows and says so when a later versions load fails', async () => {
		const replies: Record<string, unknown> = { ...ANSWERED };
		stubFetch(replies);
		render(UpdatesPage);
		await screen.findByText('Zeek');

		delete replies['/api/system/versions'];
		await refreshPage();

		expect(await screen.findByText("Couldn't refresh installed versions; showing the last figures loaded.")).toBeInTheDocument();
		expect(screen.getByText('Zeek')).toBeInTheDocument();
	});
});

describe('Software Updates page — versions table', () => {
	afterEach(() => vi.unstubAllGlobals());

	const row = (name: string, status = 'ok') =>
		({ name, category: 'docker', current_version: '1', install_type: 'docker', last_checked: '', status, details: {} });

	it('sorts by name first, and by status (most urgent first) from its header', async () => {
		stubFetch({
			...ANSWERED,
			'/api/system/versions': { versions: [row('zeek'), row('arkime', 'error'), row('logstash')], last_scan: '' },
			'/api/system/updates/available': {
				updates: [{ component: 'logstash', current_version: '1', latest_version: '2', update_type: 'minor', release_url: '', release_date: '',
					changelog: '', size_mb: null, requires_restart: false, applies_with: null }],
				last_check: '2026-11-02T21:00:00Z',
			},
		});
		render(UpdatesPage);
		await screen.findByText('zeek');
		const names = () => [...document.querySelectorAll('.component-name')].map((el) => el.textContent);

		expect(names()).toEqual(['arkime', 'logstash', 'zeek']);
		const header = screen.getByRole('columnheader', { name: /^Status/ });
		await fireEvent.click(within(header).getByRole('button'));
		if (header.getAttribute('aria-sort') !== 'descending') await fireEvent.click(within(header).getByRole('button'));

		expect(header).toHaveAttribute('aria-sort', 'descending');
		expect(names()).toEqual(['arkime', 'logstash', 'zeek']);
		await fireEvent.click(within(header).getByRole('button'));
		expect(names()).toEqual(['zeek', 'logstash', 'arkime']);
	});
});

describe('Software Updates page — refresh contract', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('registers its loader and reports ok when every request answers', async () => {
		stubFetch(ANSWERED);
		render(UpdatesPage);

		expect(get(pageRefresh).available).toBe(true);
		expect(await refreshPage()).toBe('ok');
	});

	it('reports partial when one request fails', async () => {
		stubFetch({ ...ANSWERED, '/api/system/updates/history': undefined });
		render(UpdatesPage);

		expect(await refreshPage()).toBe('partial');
	});

	it('reports failed when every request fails', async () => {
		stubFetch({});
		render(UpdatesPage);

		expect(await refreshPage()).toBe('failed');
	});

	it('unregisters when the page goes', () => {
		stubFetch(ANSWERED);
		const { unmount } = render(UpdatesPage);
		unmount();

		expect(get(pageRefresh).available).toBe(false);
	});
});
