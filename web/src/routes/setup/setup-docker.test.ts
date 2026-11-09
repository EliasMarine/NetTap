import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';

vi.mock('$app/forms', () => ({ enhance: () => ({ destroy: () => {} }) }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import SetupPage from './+page.svelte';

// "Docker is running" passed in every branch, a failed request included. /api/health answers 200
// from the web container even when the daemon is down; its `daemon` field says whether it answered.

function stubHealth(health: Response) {
	globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
		const url = String(input);
		if (url === '/api/health') return health;
		if (url === '/api/setup/storage') return new Response(JSON.stringify({ disk_free_gb: 500, source: 'daemon' }));
		return new Response(JSON.stringify({ source: 'daemon', interfaces: [] }));
	}) as typeof fetch;
}

const originalFetch = globalThis.fetch;

describe('setup wizard Docker check', () => {
	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	it('fails when the daemon is not answering', async () => {
		stubHealth(new Response(JSON.stringify({ status: 'healthy', daemon: { status: 'unreachable' } })));
		render(SetupPage, { props: { data: { username: null, setupVerified: true }, form: null } });
		expect(await screen.findByText("Docker: the NetTap daemon isn't answering")).toBeInTheDocument();
		expect(screen.queryByText('Docker is running')).not.toBeInTheDocument();
	});

	it("says it couldn't check when the request fails", async () => {
		stubHealth(new Response('', { status: 502 }));
		render(SetupPage, { props: { data: { username: null, setupVerified: true }, form: null } });
		expect(await screen.findByText("Docker: couldn't check")).toBeInTheDocument();
	});

	it('passes when the daemon answers', async () => {
		stubHealth(new Response(JSON.stringify({ status: 'healthy', daemon: { status: 'healthy' } })));
		render(SetupPage, { props: { data: { username: null, setupVerified: true }, form: null } });
		expect(await screen.findByText('Docker is running')).toBeInTheDocument();
		expect(screen.queryByText(/Docker: /)).not.toBeInTheDocument();
	});
});
