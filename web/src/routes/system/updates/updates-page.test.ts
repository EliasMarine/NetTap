import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import UpdatesPage from './+page.svelte';

const VERSIONS = {
	versions: {
		zeek: { name: 'Zeek', category: 'core', current_version: '6.0.4', install_type: 'docker', last_checked: '', status: 'ok', details: {} },
	},
	last_scan: '',
};

/** Answer each URL with its body, or HTTP 500 when it has none. */
function stubFetch(replies: Record<string, unknown>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const body = replies[String(input)];
			if (body == null) return new Response('{}', { status: 500 });
			return new Response(JSON.stringify(body), { status: 200 });
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
			'/api/system/updates/available': { updates: [], last_check: '', failed_checks: ['nettap-daemon'] },
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
			'/api/system/updates/available': { updates: [], last_check: '' },
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
		expect(screen.getByText(MALCOLM)).toBeInTheDocument();
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
});
