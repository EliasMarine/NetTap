import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Page from './+page.svelte';

// #96: a failed UniFi status read showed the form as "not configured"

function stubStatus(reply: { status: number; body?: unknown }) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) =>
			url === '/api/integrations/unifi/status'
				? { ok: reply.status < 400, status: reply.status, json: async () => reply.body }
				: { ok: false, status: 500, json: async () => ({}) },
		),
	);
}

async function openIntegrations() {
	render(Page);
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
	await fireEvent.click(screen.getByRole('button', { name: 'Integrations' }));
}

describe('Settings — UniFi status failed', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('says the UniFi status could not be read', async () => {
		stubStatus({ status: 503 });
		await openIntegrations();
		expect(screen.getByText(/Couldn't load the UniFi status: the request failed\./)).toBeInTheDocument();
	});

	it('says nothing about a failure when the status reads as not configured', async () => {
		stubStatus({
			status: 200,
			body: { configured: false, controller_url: null, site_id: null, connected: false, last_poll_time: 0, cache_counts: {}, last_error: null },
		});
		await openIntegrations();
		expect(screen.getByPlaceholderText('Paste your UniFi API key')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't load the UniFi status/)).not.toBeInTheDocument();
	});
});
