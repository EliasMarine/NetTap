import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import ToolsCyberChefPage from './+page.svelte';
import SystemCyberChefPage from '../../system/cyberchef/+page.svelte';

/** /api/cyberchef/status gets `status` (or HTTP 500 when null); recipes are empty. */
function stubFetch(status: Record<string, unknown> | null) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			if (url.startsWith('/api/cyberchef/recipes')) return new Response(JSON.stringify({ recipes: [], count: 0 }), { status: 200 });
			if (url.startsWith('/api/cyberchef/status') && status) return new Response(JSON.stringify(status), { status: 200 });
			return new Response('{}', { status: 500 });
		}),
	);
}

describe.each([
	['Tools', ToolsCyberChefPage],
	['System', SystemCyberChefPage],
])('%s CyberChef page when the status request fails (#96)', (_name, Page) => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the status could not be checked instead of "container is not running"', async () => {
		stubFetch(null);

		render(Page);

		expect(await screen.findByText("Couldn't check CyberChef status: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('Offline')).not.toBeInTheDocument();
		expect(screen.queryByText(/container is not running/)).not.toBeInTheDocument();
	});

	it('still says the container is not running when the daemon says so', async () => {
		stubFetch({ available: false, version: '', container_running: false, container_name: 'cyberchef' });

		render(Page);

		expect(await screen.findByText(/container is not running/)).toBeInTheDocument();
		expect(screen.getByText('Offline')).toBeInTheDocument();
	});
});

describe('Tools CyberChef page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const UP = { available: true, version: '10.19.4', container_running: true, container_name: 'cyberchef' };

	it('shows the loading state while the status is checked', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(ToolsCyberChefPage);
		expect(screen.getByRole('status')).toHaveTextContent('Checking CyberChef status…');
		expect(screen.getByText('Checking…')).toBeInTheDocument();
	});

	it('shows the workspace and the running chip when CyberChef is up', async () => {
		stubFetch(UP);
		render(ToolsCyberChefPage);
		expect(await screen.findByTitle('CyberChef')).toHaveAttribute('src', '/cyberchef/');
		expect(screen.getByText('Running')).toBeInTheDocument();
		expect(screen.getByRole('heading', { level: 1, name: 'CyberChef' })).toBeInTheDocument();
	});

	it('reports ok to the page refresh, failed when the status request fails, and unregisters on destroy', async () => {
		stubFetch(UP);
		const { unmount } = render(ToolsCyberChefPage);
		await screen.findByText('Running');
		expect(get(pageRefresh)).toMatchObject({ available: true, status: 'ok' });

		stubFetch(null);
		expect(await refreshPage()).toBe('failed');
		expect(get(pageRefresh).status).toBe('failed');

		unmount();
		expect(get(pageRefresh).available).toBe(false);
	});

	it('Try again re-checks the status through the refresh contract', async () => {
		stubFetch(null);
		render(ToolsCyberChefPage);
		await screen.findByText("Couldn't check CyberChef status: the request failed.");
		stubFetch(UP);
		await fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
		expect(await screen.findByText('Running')).toBeInTheDocument();
		expect(get(pageRefresh).status).toBe('ok');
	});
});
