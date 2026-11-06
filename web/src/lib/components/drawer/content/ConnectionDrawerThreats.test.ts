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

	// Each level is the system pill: colour, shape and word. NET-146: the mapping is the Alerts page's
	// and the Live drawer's (it read 1 and 2 High, 3 Medium, else Low, so severity 2 disagreed).
	it('shows each alert as a severity pill with shape and word: 1 High, 2 Medium, 3 Low, else Info', async () => {
		const alerts = [
			{ _id: 'a1', alert: { severity: 1, signature: 'SIG ONE' } },
			{ _id: 'a2', alert: { severity: 2, signature: 'SIG TWO' } },
			{ _id: 'a3', alert: { severity: 3, signature: 'SIG THREE' } },
			{ _id: 'a4', alert: { severity: 4, signature: 'SIG FOUR' } },
		];
		stubAlerts({ ok: true, body: { from: '', to: '', page: 1, size: 10, total: 4, total_pages: 1, alerts } });
		render(ConnectionDrawerContent, { connection: CONNECTION, activeTab: 'summary' });
		const expected: Array<[string, string, string]> = [
			// OLD CODE START — the old mapping
			// ['SIG ONE', 'High', 'sev-high'],
			// ['SIG TWO', 'High', 'sev-high'],
			// ['SIG THREE', 'Medium', 'sev-medium'],
			// ['SIG FOUR', 'Low', 'sev-low'],
			// OLD CODE END
			['SIG ONE', 'High', 'sev-high'],
			['SIG TWO', 'Medium', 'sev-medium'],
			['SIG THREE', 'Low', 'sev-low'],
			['SIG FOUR', 'Info', 'sev-info'],
		];
		for (const [sig, word, cls] of expected) {
			const pill = (await screen.findByText(sig)).previousElementSibling as HTMLElement;
			expect(pill).toHaveTextContent(word);
			expect(pill).toHaveClass('sev', cls);
			expect(pill.querySelector('svg')).not.toBeNull();
		}
	});
});

describe('Connection drawer — flow diagram', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('cuts a long destination ASN to 16 characters and an ellipsis, so it fits at the 11 px token', () => {
		stubAlerts({ ok: false });
		const connection = { ...CONNECTION, destination: { ...CONNECTION.destination, as: { full: 'Example Networks International' } } };
		const { container } = render(ConnectionDrawerContent, { connection, activeTab: 'flow' });
		const texts = [...container.querySelectorAll('svg text')].map((t) => t.textContent?.trim());
		expect(texts).toContain('Example Networks…');
	});
});

// NET-166: the drawer's byte figures are decimal (the 1024-based code read 976.6 KB for 1,000,000 bytes)
describe('Connection drawer — byte figures', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows what each side sent in decimal units', async () => {
		stubAlerts({ ok: true, body: { from: '', to: '', page: 1, size: 10, total: 0, total_pages: 0, alerts: [] } });
		const connection = { ...CONNECTION, source: { ...CONNECTION.source, bytes: 1_000_000 }, destination: { ...CONNECTION.destination, bytes: 1_500 } };
		render(ConnectionDrawerContent, { connection, activeTab: 'summary' });
		const value = (label: string) => screen.getByText(label).nextElementSibling?.textContent?.trim();
		expect(value('Sent by source')).toBe('1.0 MB');
		expect(value('Sent by destination')).toBe('1.5 KB');
	});
});
