import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import HomePage from './+page.svelte';

// jsdom has no ResizeObserver; the bandwidth chart needs one to mount
vi.stubGlobal(
	'ResizeObserver',
	class {
		observe() {}
		unobserve() {}
		disconnect() {}
	},
);

describe('Home — application layer labels (#20)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('calls connections with no identified protocol "Unidentified", not "Unknown"', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url.startsWith('/api/traffic/protocols')) {
					const body = { protocols: [{ name: 'udp', count: 9 }], services: [{ name: 'unknown', count: 8700 }, { name: 'dns', count: 300 }] };
					return { ok: true, status: 200, json: async () => body };
				}
				return { ok: false, status: 503, json: async () => ({}) };
			}),
		);
		render(HomePage);

		// sentence case now (Voice rules); was 'UNIDENTIFIED' beside upper-case protocol names
		expect(await screen.findByText('Unidentified')).toBeInTheDocument();
		expect(screen.getAllByText('DNS').length).toBeGreaterThan(0);
		expect(screen.queryByText(/^unknown$/i)).not.toBeInTheDocument();
	});
});

describe('Home — the Unidentified bar counts conversations only (NET-219)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	const SERVICES = [
		{ name: 'unknown', count: 304_800 },
		{ name: 'ssl', count: 90_000 },
		{ name: 'quic', count: 12_000 },
		{ name: 'dns', count: 8_000 },
	];

	function stubProtocols(extra: Record<string, unknown>) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url.startsWith('/api/traffic/protocols')) {
					const body = { protocols: [{ name: 'tcp', count: 9 }], services: SERVICES, ...extra };
					return { ok: true, status: 200, json: async () => body };
				}
				return { ok: false, status: 503, json: async () => ({}) };
			}),
		);
	}

	/** The Application layer bars, top to bottom, as "label value" */
	async function bars(container: HTMLElement): Promise<string[]> {
		await screen.findByText('Unidentified');
		return [...container.querySelectorAll('.bar-row')].map(
			(row) => `${row.firstElementChild?.textContent} ${row.querySelector('.v')?.textContent}`,
		);
	}

	const NOTE = /^Not in the bars:/;

	it('shows conversations, re-sorted below the bigger services, with both clauses in the note', async () => {
		stubProtocols({ unidentified: { conversations: 647, one_way: 281_312, icmp: 22_841 } });
		const { container } = render(HomePage);

		expect(await bars(container)).toEqual(['SSL 90K', 'QUIC 12K', 'DNS 8K', 'Unidentified 647']);
		expect(screen.getByText(NOTE).textContent).toBe(
			'Not in the bars: 281.3K unidentified connections with no data sent in at least one direction, and 22.8K ICMP exchanges (pings and network notices).',
		);
	});

	it('drops the one-way clause when there are none', async () => {
		stubProtocols({ unidentified: { conversations: 304_799, one_way: 0, icmp: 1 } });
		const { container } = render(HomePage);

		expect((await bars(container))[0]).toBe('Unidentified 304.8K');
		expect(screen.getByText(NOTE).textContent).toBe('Not in the bars: 1 ICMP exchange (pings and network notices).');
	});

	it('drops the ICMP clause when there are none', async () => {
		stubProtocols({ unidentified: { conversations: 300_000, one_way: 4_800, icmp: 0 } });
		const { container } = render(HomePage);

		await bars(container);
		expect(screen.getByText(NOTE).textContent).toBe(
			'Not in the bars: 4.8K unidentified connections with no data sent in at least one direction.',
		);
	});

	it('drops an Unidentified bar of 0 and keeps the note', async () => {
		stubProtocols({ unidentified: { conversations: 0, one_way: 300, icmp: 4 } });
		const { container } = render(HomePage);

		expect(await screen.findByText(NOTE)).toBeInTheDocument();
		const labels = [...container.querySelectorAll('.bar-row')].map((row) => row.firstElementChild?.textContent);
		expect(labels).toEqual(['SSL', 'QUIC', 'DNS']);
	});

	it('hides the note when nothing is left out', async () => {
		stubProtocols({ unidentified: { conversations: 304_800, one_way: 0, icmp: 0 } });
		const { container } = render(HomePage);

		expect((await bars(container))[0]).toBe('Unidentified 304.8K');
		expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
	});

	it('sorts before it keeps the top 8, so a small Unidentified bar gives its place to a ninth service', async () => {
		const nine = ['http', 'dns', 'ntp', 'ssh', 'smtp', 'imap', 'ldap', 'sip', 'rdp'].map((name, i) => ({ name, count: 9_000 - i * 1_000 }));
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url.startsWith('/api/traffic/protocols')) {
					const body = {
						protocols: [{ name: 'tcp', count: 9 }],
						services: [{ name: 'unknown', count: 500_000 }, ...nine],
						unidentified: { conversations: 100, one_way: 499_900, icmp: 0 },
					};
					return { ok: true, status: 200, json: async () => body };
				}
				return { ok: false, status: 503, json: async () => ({}) };
			}),
		);
		const { container } = render(HomePage);

		await screen.findByText(NOTE);
		const labels = [...container.querySelectorAll('.bar-row')].map((row) => row.firstElementChild?.textContent);
		expect(labels).toEqual(['HTTP', 'DNS', 'NTP', 'SSH', 'SMTP', 'IMAP', 'LDAP', 'SIP']);
	});

	it('falls back to the unknown count, with no note, when the reply has no split', async () => {
		stubProtocols({});
		const { container } = render(HomePage);

		expect(await bars(container)).toEqual(['Unidentified 304.8K', 'SSL 90K', 'QUIC 12K', 'DNS 8K']);
		expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
	});
});
