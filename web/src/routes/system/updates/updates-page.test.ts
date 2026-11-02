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

	it('still reads Up to Date when the update list loads and is empty', async () => {
		stubFetch({ '/api/system/versions': VERSIONS, '/api/system/updates/available': { updates: [], last_check: '' } });

		render(UpdatesPage);

		expect(await screen.findByText('Up to Date')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
	});
});
