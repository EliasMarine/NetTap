import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ConnectionDrawerContent from './ConnectionDrawerContent.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

// #96: a failed related-connections request read as "0 Total Sessions" / "No related connections found".

const CONNECTION = { _id: 'c1', source: { ip: '192.168.1.20', port: 50000 }, destination: { ip: '8.8.8.8', port: 53 } };

function stubRelated(body: unknown | null): void {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (url: string) =>
			url.startsWith('/api/traffic/connections/related') && body !== null
				? { ok: true, status: 200, json: async () => body }
				: { ok: false, status: 503, json: async () => ({}) },
		),
	);
}

describe('Connection drawer — Related tab', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the request failed instead of "No related connections found"', async () => {
		stubRelated(null);
		render(ConnectionDrawerContent, { connection: CONNECTION, activeTab: 'related' });
		expect(await screen.findByText("Couldn't load related connections: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('No related connections found')).not.toBeInTheDocument();
		expect(screen.queryByText('Total sessions')).not.toBeInTheDocument();
	});

	it('shows the related totals when the request succeeds', async () => {
		stubRelated({
			from: '', to: '', src_ip: '192.168.1.20', dst_ip: '8.8.8.8',
			total_connections: 7, total_bytes: 2048, protocols: ['udp'],
			first_seen: null, last_seen: null, connections: [],
		});
		render(ConnectionDrawerContent, { connection: CONNECTION, activeTab: 'related' });
		expect(await screen.findByText('Total sessions')).toBeInTheDocument();
		expect(screen.getByText('7')).toBeInTheDocument();
	});
});
