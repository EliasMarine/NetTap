import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ConnectionDrawerContent from './ConnectionDrawerContent.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

// #96: getAlerts turned an HTTP error into an empty list, so the Threat Context section said
// "No associated alerts found" when the lookup had failed.

const CONNECTION = {
	_id: 'c1',
	source: { ip: '192.168.1.10', port: 51515 },
	destination: { ip: '203.0.113.7', port: 443 },
	network: { transport: 'tcp' },
};

function stubAlerts(reply: { ok: boolean; body?: unknown }): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) =>
			url.startsWith('/api/alerts')
				? { ok: reply.ok, status: reply.ok ? 200 : 502, json: async () => reply.body ?? {} }
				: { ok: false, status: 503, json: async () => ({}) },
		),
	);
}

describe('Connection drawer — threat context', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the alert lookup failed instead of "No associated alerts found"', async () => {
		stubAlerts({ ok: false });
		render(ConnectionDrawerContent, { connection: CONNECTION, activeTab: 'summary' });
		expect(await screen.findByText("Couldn't check for associated alerts: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No associated alerts found')).not.toBeInTheDocument();
	});

	it('still says none were found when the lookup succeeds empty', async () => {
		stubAlerts({ ok: true, body: { from: '', to: '', page: 1, size: 10, total: 0, total_pages: 0, alerts: [] } });
		render(ConnectionDrawerContent, { connection: CONNECTION, activeTab: 'summary' });
		expect(await screen.findByText('No associated alerts found')).toBeInTheDocument();
	});
});
