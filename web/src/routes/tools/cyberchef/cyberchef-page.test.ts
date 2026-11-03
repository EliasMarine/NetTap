import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
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
