import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { refreshPage } from '$lib/stores/pageRefresh';
import { LAN_POLICY } from '../../../../e2e/visual/fixtures/drilldown';
import { POSTURE_DNS, POSTURE_ENCRYPTION } from '../../../../e2e/visual/fixtures/traffic';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';

// Posture category pages: one snapshot per load, replaced whole; another category never shows it

const pageStore = vi.hoisted(() => ({ value: null as unknown as ReturnType<typeof writable> }));
vi.mock('$app/stores', async () => {
	const { writable: w } = await import('svelte/store');
	pageStore.value = w({ url: new URL('http://localhost/compliance/encryption'), params: { category: 'encryption' } });
	return { page: pageStore.value };
});

const { default: Page } = await import('./+page.svelte');

const goTo = (category: string) => pageStore.value.set({ url: new URL(`http://localhost/compliance/${category}`), params: { category } });

type Reply = unknown | 'fail' | Promise<unknown>;
const REPLIES: Record<string, Reply> = {
	'/api/network/lan': LAN_POLICY,
	'/api/system/health': { pipeline: { state: 'fresh', newest_record_at: null, age_seconds: 40, threshold_seconds: 900, sensors: {}, checked_at: '' } },
	'/api/devices/registry': { devices: [{ ips: ['192.168.1.20'], hostname: null, custom_name: 'Laptop', last_seen: '2026-11-15T00:00:00Z', first_seen: '2026-01-01T00:00:00Z' }], total: 1 },
	'/api/traffic/protocols': { from: '', to: '', protocols: [], services: [{ name: 'http', count: 250 }, { name: 'ssl', count: 750 }], encryption: { eligible: 21300, encrypted: 19800 }, dns: { plain: 5400, over_tls: 60 } },
	'/api/posture/encryption': POSTURE_ENCRYPTION,
	'/api/posture/dns-security': POSTURE_DNS,
	'/api/alerts/count': { from: '', to: '', counts: { total: 757, high: 295, medium: 219, low: 243 } },
	'/api/investigations/stats': { total: 0, by_status: {}, by_severity: {} },
	'/api/devices/count': { from: '', to: '', count: 3 },
	'/api/risk/scores': { devices: [{ ip: '192.168.1.20', score: 10, level: 'low', factors: [] }] },
	'/api/alerts/top-signatures': { from: '', to: '', complete: true, examined: 2, signatures: [{ signature: 'ET INFO Spotify P2P Client', count: 235, severity: 3 }, { signature: null, count: 4, severity: 2 }] },
	'/api/iot/network-isolation': { segmentation_score: null, segmentation_grade: null, pairs: [], recommendation: '' },
	'/api/capture/mode': { mode: 'bridge', interface: 'br0' },
	'/api/capture/stats': { loss_window: { state: 'measuring', interface: null, window: null, cumulative: null } },
};

let calls: URL[] = [];
function stubDaemon(over: Record<string, Reply> = {}) {
	calls = [];
	const replies = { ...REPLIES, ...over };
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const url = new URL(input, 'http://localhost');
			calls.push(url);
			const body = replies[url.pathname];
			if (body instanceof Promise) return body;
			if (body === undefined || body === 'fail') return { ok: false, status: 502, json: async () => ({ error: 'The posture search failed' }) };
			return { ok: true, status: 200, json: async () => body };
		}),
	);
}
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const kpi = (label: string) => screen.getAllByText(label).map((e) => e.closest('.kpi')).find(Boolean) as HTMLElement;
const card = (title: string) => screen.getByRole('heading', { name: title }).closest('.card') as HTMLElement;
const call = (path: string) => calls.find((u) => u.pathname === path)!;
const query = (href: string | null) => Object.fromEntries(new URL(href!, 'http://x').searchParams);
const loadedScore = (value: string) => vi.waitFor(() => expect(kpi('Score')).toHaveTextContent(value));

describe('Security posture category page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		goTo('encryption');
	});

	it('shows loading, not zeros, before the first answer', () => {
		stubDaemon({ '/api/traffic/protocols': new Promise(() => {}), '/api/posture/encryption': new Promise(() => {}) });
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'Encryption' })).toBeInTheDocument();
		expect(kpi('Score')).toHaveTextContent('—');
		expect(screen.getAllByRole('status').some((s) => s.getAttribute('aria-busy') === 'true')).toBe(true);
	});

	it('shows the score, what drives it, findings, steps and sources over one window', async () => {
		stubDaemon();
		const { container } = render(Page);
		await loadedScore('93');
		expect(within(screen.getByText('Security posture').closest('.eyebrow') as HTMLElement).getByRole('link')).toHaveAttribute('href', '/compliance');
		expect(screen.getByText('19,800 encrypted ÷ 21,300 connections that can be encrypted = 93%')).toBeInTheDocument();
		// both requests carried the same window
		const [p, d] = [call('/api/traffic/protocols'), call('/api/posture/encryption')];
		expect(d.searchParams.get('from')).toBe(p.searchParams.get('from'));
		expect(d.searchParams.get('to')).toBe(p.searchParams.get('to'));
		expect((Date.parse(p.searchParams.get('to')!) - Date.parse(p.searchParams.get('from')!)) / 3_600_000).toBe(24);
		// only the inputs Encryption reads
		expect(calls.some((u) => u.pathname === '/api/risk/scores')).toBe(false);

		const findings = within(card('Findings')).getByRole('table', { name: 'Encryption findings' });
		expect(within(findings).getByRole('columnheader', { name: /^Count/ })).toBeInTheDocument();
		const laptop = within(findings).getAllByRole('row').find((r) => r.textContent?.includes('Ports BitTorrent apps use'))!;
		expect(laptop).toHaveTextContent('Laptop');
		expect(within(laptop).getByRole('link', { name: '192.168.1.20' })).toHaveAttribute('href', '/devices/192.168.1.20');

		const steps = card('How to improve');
		expect(within(steps).getByText(/Start with Laptop: 73%/)).toBeInTheDocument();
		const telnet = within(steps).getAllByRole('link', { name: 'Open in Log Explorer' })[0];
		expect(query(telnet.getAttribute('href'))).toMatchObject({ type: 'zeek.conn', from: POSTURE_ENCRYPTION.from, to: POSTURE_ENCRYPTION.to, range: '24h' });

		for (const link of within(card('Learn more')).getAllByRole('link')) {
			expect(link).toHaveAttribute('target', '_blank');
			expect(link).toHaveAttribute('rel', 'noopener noreferrer');
		}
		expectNoNestedInteractive(container);
	});

	it('errors only the cards built on a failed detail request, with Try again', async () => {
		stubDaemon({ '/api/posture/encryption': 'fail' });
		render(Page);
		await loadedScore('93');
		const findings = card('Findings');
		expect(within(findings).getByText("Couldn't load the findings: the request failed.")).toBeInTheDocument();
		expect(within(findings).getByRole('button', { name: 'Try again' })).toBeInTheDocument();
		expect(kpi('Payload both ways')).toHaveTextContent('—');
		// review L5: no "Nothing to change" when the steps' request failed
		const steps = card('How to improve');
		expect(within(steps).getByText("Couldn't load the recommendations: the request failed.")).toBeInTheDocument();
		expect(within(steps).queryByText('Nothing to change from what NetTap saw')).toBeNull();
	});

	it("says which score input failed instead of scoring a stand-in", async () => {
		stubDaemon({ '/api/traffic/protocols': 'fail' });
		render(Page);
		await vi.waitFor(() => expect(within(card('What drives this score')).getByText("Couldn't load traffic protocols: the request failed.")).toBeInTheDocument());
		expect(kpi('Score')).toHaveTextContent('—');
	});

	it('keeps the whole last snapshot when a refresh of the same category fails (R1-5, R2-4)', async () => {
		stubDaemon();
		render(Page);
		await loadedScore('93');
		const before = screen.getAllByRole('link', { name: 'Open in Log Explorer' }).map((a) => a.getAttribute('href'));
		stubDaemon({ '/api/traffic/protocols': { ...(REPLIES['/api/traffic/protocols'] as object), encryption: { eligible: 100, encrypted: 1 } }, '/api/posture/encryption': 'fail' });
		expect(await refreshPage()).toBe('partial');
		expect(screen.getByText(/Couldn't refresh this category; showing the last figures loaded/)).toBeInTheDocument();
		expect(kpi('Score')).toHaveTextContent('93');
		expect(screen.getAllByRole('link', { name: 'Open in Log Explorer' }).map((a) => a.getAttribute('href'))).toEqual(before);
	});

	it('never shows Encryption figures on DNS security when the DNS request fails (R2-2)', async () => {
		stubDaemon();
		render(Page);
		await loadedScore('93');
		stubDaemon({ '/api/traffic/protocols': 'fail', '/api/posture/dns-security': 'fail' });
		goTo('dns-security');
		await vi.waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'DNS security' })).toBeInTheDocument());
		await vi.waitFor(() => expect(within(card('What drives this score')).getByText("Couldn't load traffic protocols: the request failed.")).toBeInTheDocument());
		expect(screen.queryByText(/encrypted ÷/)).toBeNull();
		expect(screen.queryByText(/Couldn't refresh/)).toBeNull();
	});

	it('drops an Encryption reply that finishes after the page moved to DNS security (R2-2)', async () => {
		let finishEncryption: (v: unknown) => void = () => {};
		stubDaemon({ '/api/posture/encryption': new Promise((resolve) => (finishEncryption = resolve)) });
		render(Page);
		stubDaemon();
		goTo('dns-security');
		await loadedScore('1');
		finishEncryption(ok(POSTURE_ENCRYPTION));
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.getByRole('heading', { level: 1, name: 'DNS security' })).toBeInTheDocument();
		expect(screen.getByText('60 DNS-over-TLS ÷ (5,400 plain + 60 DNS-over-TLS) = 1%')).toBeInTheDocument();
		expect(screen.queryByText(/encrypted ÷/)).toBeNull();
	});

	it('links rules to their page over the snapshot window, and a rule with no name to the Alerts list (R2-4)', async () => {
		goTo('alert-response');
		stubDaemon();
		render(Page);
		await loadedScore('0');
		const sent = call('/api/alerts/count');
		const rule = within(card('Findings')).getByRole('link', { name: 'ET INFO Spotify P2P Client' });
		expect(rule.getAttribute('href')).toMatch(/^\/alerts\/rule\/ET%20INFO%20Spotify%20P2P%20Client\?/);
		expect(query(rule.getAttribute('href'))).toEqual({ from: sent.searchParams.get('from'), to: sent.searchParams.get('to'), range: '24h' });
		expect(within(card('Findings')).getByRole('link', { name: 'Alerts with no rule name' }).getAttribute('href')).toMatch(/^\/alerts\?no_rule_name=true&/);
		expect(kpi('Investigations (all time)')).toHaveTextContent('0 of 0');
	});

	it('shows each source on its own: isolation not measured beside the baseline findings', async () => {
		goTo('network-segmentation');
		stubDaemon();
		render(Page);
		await loadedScore('80');
		const findings = card('Findings');
		expect(within(findings).getByText(/2 device\(s\) without a baseline/)).toBeInTheDocument();
		expect(within(findings).getByText(/No smart \(IoT\) devices detected yet/)).toBeInTheDocument();
	});

	it('renders two steps with the same text (review L7: keyed by position)', async () => {
		goTo('network-segmentation');
		const pair = { iot_device: { mac: '02:00:5e:10:00:50', name: 'Camera', ip: '192.168.1.50' }, internal_target: { ip: '192.168.1.20', hostname: null }, risk: 'high', connection_count: 4, ports: [445], description: 'Camera reached a computer.' };
		stubDaemon({ '/api/iot/network-isolation': { segmentation_score: 40, segmentation_grade: 'F', recommendation: '', pairs: [pair, { ...pair, ports: [139] }] } });
		render(Page);
		await loadedScore('80');
		expect(within(card('How to improve')).getAllByText('Move Camera to a guest or IoT network: it reached Laptop.')).toHaveLength(2);
	});

	it('shows the capture mode and pipeline findings for Monitoring coverage', async () => {
		goTo('monitoring-coverage');
		stubDaemon();
		render(Page);
		await loadedScore('33');
		expect(within(card('Findings')).getByText('Inline bridge mode hides your devices')).toBeInTheDocument();
		expect(within(card('Findings')).getByText(/Packet loss:/)).toBeInTheDocument();
		expect(kpi('Data pipeline')).toHaveTextContent('Running');
	});
});
