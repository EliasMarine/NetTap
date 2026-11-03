import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import {
	getAlerts,
	getAlertCount,
	getAlertTimeline,
	getAlertTopSignatures,
	getAlertTopIps,
	getEnhancedCategories,
	getSmartAlertSummary,
} from '$api/alerts';
import Page from './+page.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/alerts') }),
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$api/alerts', async (importOriginal) => {
	const notUnderTest = () => Promise.reject(new Error('not under test'));
	return {
		...(await importOriginal<typeof import('$api/alerts')>()),
		getAlerts: vi.fn(),
		getAlertCount: vi.fn(notUnderTest),
		getAlertTimeline: vi.fn(notUnderTest),
		getAlertTopSignatures: vi.fn(notUnderTest),
		getAlertTopIps: vi.fn(notUnderTest),
		getEnhancedCategories: vi.fn(notUnderTest),
		getSmartAlertSummary: vi.fn(notUnderTest),
	};
});

describe('Alerts', () => {
	it('should export a Svelte component', async () => {
		const module = await import('./+page.svelte');
		expect(module.default).toBeDefined();
	});
});

// ---------------------------------------------------------------------------
// Rendered page: auto-refresh keeps the current page
// ---------------------------------------------------------------------------

function alertsPage(page: number) {
	return {
		from: '',
		to: '',
		page,
		size: 50,
		total: 250,
		total_pages: 5,
		alerts: [
			{
				_id: `a${page}`,
				_index: 'suricata-x',
				timestamp: '2026-10-29T10:00:00Z',
				alert: { signature: `Sig on page ${page}`, signature_id: 2000 + page, severity: 2, category: 'misc' },
				src_ip: '10.0.0.5',
				dest_ip: '8.8.8.8',
				acknowledged: false,
			},
		],
	};
}

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

// jsdom has no ResizeObserver; the timeline chart needs one to mount
vi.stubGlobal(
	'ResizeObserver',
	class {
		observe() {}
		unobserve() {}
		disconnect() {}
	},
);

describe('Alerts — auto-refresh', () => {
	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
		vi.mocked(getAlerts).mockImplementation(async (opts = {}) => alertsPage(opts.page ?? 1));
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.clearAllMocks();
	});

	it('reloads the page the user is on, not page 1', async () => {
		render(Page);
		await flush();
		await fireEvent.click(screen.getByRole('button', { name: 'Next' }));
		await flush();
		expect(screen.getByText('Sig on page 2')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'Auto' }));
		vi.mocked(getAlerts).mockClear();
		vi.advanceTimersByTime(15_000);
		await flush();

		expect(getAlerts).toHaveBeenCalledWith(expect.objectContaining({ page: 2 }));
		expect(getAlerts).not.toHaveBeenCalledWith(expect.objectContaining({ page: 1 }));
		expect(screen.getByText('Sig on page 2')).toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// #96: a failed request returned an empty list or zero counts, so the page said "No Alerts",
// "No signatures found" and showed 0 in every stat card when nothing had loaded.
// ---------------------------------------------------------------------------

describe('Alerts — failed requests', () => {
	afterEach(() => {
		vi.clearAllMocks();
	});

	it('says each section could not be loaded instead of showing none or 0', async () => {
		// every other getter is mocked to reject (notUnderTest)
		vi.mocked(getAlerts).mockRejectedValue(new Error('Alerts failed: HTTP 502'));
		render(Page);
		await flush();

		expect(screen.getByText("Couldn't load alerts")).toBeInTheDocument();
		expect(screen.queryByText('No Alerts')).not.toBeInTheDocument();
		expect(screen.getByText(/Couldn't load the alert timeline/)).toBeInTheDocument();
		expect(screen.getByText(/Couldn't load alert categories/)).toBeInTheDocument();
		expect(screen.getByText(/Couldn't load top signatures/)).toBeInTheDocument();
		expect(screen.queryByText('No signatures found')).not.toBeInTheDocument();
		expect(screen.getByText(/Couldn't load affected devices/)).toBeInTheDocument();
		expect(screen.getByText(/Couldn't load source IPs/)).toBeInTheDocument();
		expect(screen.queryByText('0')).not.toBeInTheDocument();
	});

	it('still says there are none when every request succeeds empty', async () => {
		const range = { from: '', to: '' };
		vi.mocked(getAlerts).mockResolvedValue({ ...range, page: 1, size: 50, total: 0, total_pages: 0, alerts: [] });
		vi.mocked(getAlertCount).mockResolvedValue({ ...range, counts: { total: 0, high: 0, medium: 0, low: 0 } });
		vi.mocked(getAlertTimeline).mockResolvedValue({ ...range, interval: '1h', buckets: [] });
		vi.mocked(getAlertTopSignatures).mockResolvedValue({ ...range, signatures: [] });
		vi.mocked(getAlertTopIps).mockResolvedValue({ ...range, direction: 'dest', ips: [] });
		vi.mocked(getEnhancedCategories).mockResolvedValue({ ...range, categories: [] });
		vi.mocked(getSmartAlertSummary).mockResolvedValue({
			...range, threat_score: 0, threat_level: 'none', total_groups: 0, total_events: 0, categories: {}, top_threats: [],
		});
		render(Page);
		await flush();

		expect(screen.getByText('No Alerts')).toBeInTheDocument();
		expect(screen.getByText('No signatures found')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Rendered page: sorting (sort sweep on the G11)
// ---------------------------------------------------------------------------

describe('Alerts — sorting', () => {
	afterEach(() => {
		vi.clearAllMocks();
	});

	const alert = (id: string, severity: number, proto: string, src: string) => ({
		_id: id, _index: 'suricata-x', timestamp: '2026-10-29T10:00:00Z',
		alert: { signature: `Sig ${id}`, signature_id: 1, severity, category: 'misc' },
		src_ip: src, dest_ip: '8.8.8.8', proto, acknowledged: false,
	});

	it('puts the most severe first on the first Severity click, and sorts Protocol', async () => {
		vi.mocked(getAlerts).mockResolvedValue({
			from: '', to: '', page: 1, size: 50, total: 3, total_pages: 1,
			alerts: [alert('low', 3, 'udp', '10.0.0.26'), alert('high', 1, 'tcp', '10.0.0.235'), alert('med', 2, 'icmp', '10.0.0.9')],
		});
		const { container } = render(Page);
		await flush();
		const sigs = () => [...container.querySelectorAll('td.sig-cell')].map((td) => td.textContent?.trim());
		const header = (label: string) => [...container.querySelectorAll('th button.sort-btn')].find((b) => b.textContent?.startsWith(label))!;

		// Suricata's 1 is the most severe: the first (descending) click used to put LOW on top
		await fireEvent.click(header('Severity'));
		expect(sigs()).toEqual(['Sig high', 'Sig med', 'Sig low']);

		await fireEvent.click(header('Protocol')); // text columns start A→Z
		expect(sigs()).toEqual(['Sig med', 'Sig high', 'Sig low']); // icmp, tcp, udp
		await fireEvent.click(header('Protocol'));
		expect(sigs()).toEqual(['Sig low', 'Sig high', 'Sig med']);
	});
});
