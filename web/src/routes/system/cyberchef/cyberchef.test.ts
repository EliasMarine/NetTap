import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { pageRefresh, refreshPage } from '$lib/stores/pageRefresh';
import CyberChefPage from './+page.svelte';

const RUNNING = { available: true, version: '10.5.2', container_running: true, container_name: 'nettap-cyberchef' };
const RECIPES = {
	recipes: [
		{ name: 'Base64 decode', description: 'Decode Base64 text', category: 'decode', recipe_fragment: 'From_Base64' },
		{ name: 'URL decode', description: 'Decode %-escapes', category: 'decode', recipe_fragment: 'URL_Decode' },
	],
	count: 2,
};

/** Answer each URL from `replies` (status 200), anything else with a 503. */
function stubFetch(replies: Record<string, unknown>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const body = replies[String(input)];
			return body ? new Response(JSON.stringify(body), { status: 200 }) : new Response('{}', { status: 503 });
		}),
	);
}

const calls = (url: string) => vi.mocked(fetch).mock.calls.filter(([u]) => String(u) === url).length;

describe('CyberChef page states', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('shows a loading card while the status is pending', () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})));

		render(CyberChefPage);

		expect(screen.getByText('Checking CyberChef status').closest('[role="status"]')).toHaveAttribute('aria-busy', 'true');
		expect(screen.getByText('Checking…')).toBeInTheDocument();
	});

	it('says the status check failed, not that CyberChef is offline, and retries (#96)', async () => {
		stubFetch({ '/api/cyberchef/recipes': RECIPES });

		render(CyberChefPage);

		const error = (await screen.findByText("Couldn't check CyberChef status: the request failed.")).closest('[role="alert"]') as HTMLElement;
		expect(screen.queryByText('Offline')).not.toBeInTheDocument();
		expect(screen.getByText('Unknown')).toBeInTheDocument();
		const before = calls('/api/cyberchef/status');
		await fireEvent.click(within(error).getByRole('button', { name: 'Try again' }));
		await vi.waitFor(() => expect(calls('/api/cyberchef/status')).toBe(before + 1));
	});

	it('says the container is not running when the daemon reports it unavailable', async () => {
		stubFetch({ '/api/cyberchef/status': { ...RUNNING, available: false, container_running: false }, '/api/cyberchef/recipes': RECIPES });

		render(CyberChefPage);

		expect(await screen.findByText("CyberChef isn't running")).toBeInTheDocument();
		expect(screen.getByText('Offline')).toBeInTheDocument();
		expect(screen.queryByTitle('CyberChef')).not.toBeInTheDocument();
		const before = calls('/api/cyberchef/status');
		await fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
		await vi.waitFor(() => expect(calls('/api/cyberchef/status')).toBe(before + 1));
	});

	it('shows the recipes and the CyberChef frame when it is running', async () => {
		stubFetch({ '/api/cyberchef/status': RUNNING, '/api/cyberchef/recipes': RECIPES });

		render(CyberChefPage);

		expect(await screen.findByText('Running')).toBeInTheDocument();
		expect(screen.getByRole('group', { name: 'decode recipes' })).toBeInTheDocument();
		expect(screen.getByTitle('CyberChef')).toHaveAttribute('src', '/cyberchef/');
	});

	it('shows the empty recipes state when there are none', async () => {
		stubFetch({ '/api/cyberchef/status': RUNNING, '/api/cyberchef/recipes': { recipes: [], count: 0 } });

		render(CyberChefPage);

		expect(await screen.findByText('No quick recipes')).toBeInTheDocument();
		expect(screen.getByTitle('CyberChef')).toBeInTheDocument();
	});
});

describe('CyberChef page recipes', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('builds the recipe URL from the pasted data and opens it in the frame', async () => {
		stubFetch({ '/api/cyberchef/status': RUNNING, '/api/cyberchef/recipes': RECIPES, '/api/cyberchef/url': { url: '/cyberchef/#recipe=From_Base64' } });
		render(CyberChefPage);

		const pill = await screen.findByRole('button', { name: 'Base64 decode' });
		await fireEvent.click(pill);
		expect(pill).toHaveAttribute('aria-pressed', 'true');
		const apply = screen.getByRole('button', { name: 'Apply recipe' });
		expect(apply).toBeDisabled();
		await fireEvent.input(screen.getByLabelText('Recipe: Base64 decode'), { target: { value: 'aGk=' } });
		await fireEvent.click(apply);

		await vi.waitFor(() => expect(screen.getByTitle('CyberChef')).toHaveAttribute('src', '/cyberchef/#recipe=From_Base64'));
		const body = JSON.parse(String(vi.mocked(fetch).mock.calls.find(([u]) => String(u) === '/api/cyberchef/url')?.[1]?.body));
		expect(body).toEqual({ recipe_fragment: 'From_Base64', input_data: 'aGk=' });
		await fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
		expect(screen.getByTitle('CyberChef')).toHaveAttribute('src', '/cyberchef/');
	});

	it('says why building the URL failed', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (input: RequestInfo | URL) => {
				const url = String(input);
				if (url === '/api/cyberchef/status') return new Response(JSON.stringify(RUNNING), { status: 200 });
				if (url === '/api/cyberchef/recipes') return new Response(JSON.stringify(RECIPES), { status: 200 });
				return new Response(JSON.stringify({ error: 'Input too large' }), { status: 400 });
			}),
		);
		render(CyberChefPage);

		await fireEvent.click(await screen.findByRole('button', { name: 'URL decode' }));
		await fireEvent.input(screen.getByLabelText('Recipe: URL decode'), { target: { value: '%41' } });
		await fireEvent.click(screen.getByRole('button', { name: 'Apply recipe' }));

		expect((await screen.findByText('Input too large')).closest('[role="alert"]')).not.toBeNull();
	});
});

describe('CyberChef page refresh contract', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('registers its loader and reports ok when both requests answer', async () => {
		stubFetch({ '/api/cyberchef/status': RUNNING, '/api/cyberchef/recipes': RECIPES });
		render(CyberChefPage);

		expect(get(pageRefresh).available).toBe(true);
		expect(await refreshPage()).toBe('ok');
	});

	it('reports partial when the recipes request throws, and keeps the status', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (input: RequestInfo | URL) => {
				if (String(input) === '/api/cyberchef/status') return new Response(JSON.stringify(RUNNING), { status: 200 });
				throw new TypeError('Failed to fetch');
			}),
		);
		render(CyberChefPage);

		expect(await refreshPage()).toBe('partial');
		expect(await screen.findByText("Couldn't load the quick recipes: the request failed.")).toBeInTheDocument();
		expect(screen.getByText('Running')).toBeInTheDocument();
	});

	it('reports failed when both requests fail', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
		render(CyberChefPage);

		expect(await refreshPage()).toBe('failed');
	});

	it('keeps a status that loaded and says a later check failed', async () => {
		stubFetch({ '/api/cyberchef/status': RUNNING, '/api/cyberchef/recipes': RECIPES });
		render(CyberChefPage);
		await screen.findByText('Running');

		stubFetch({ '/api/cyberchef/recipes': RECIPES });
		await refreshPage();

		expect(await screen.findByText("Couldn't refresh the CyberChef status; showing the last figures loaded.")).toBeInTheDocument();
		expect(screen.getByTitle('CyberChef')).toBeInTheDocument();
	});
});
