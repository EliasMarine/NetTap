import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import * as captureApi from '$api/capture';
import CaptureHealthPanel from './CaptureHealthPanel.svelte';

vi.mock('$api/capture', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/capture')>()),
	getCaptureHealth: vi.fn(),
	getCaptureStats: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Rendered panel: mode badge (CR-212)
// ---------------------------------------------------------------------------

describe('CaptureHealthPanel mode badge', () => {
	afterEach(() => {
		vi.clearAllMocks();
	});

	async function renderWithMode(mode: string) {
		vi.mocked(captureApi.getCaptureHealth).mockResolvedValue({
			mode,
			status: 'normal',
			capture_interface: 'enp1s0',
			link_up: true,
			promisc_enabled: true,
			issues: [],
		});
		vi.mocked(captureApi.getCaptureStats).mockResolvedValue({
			capture_interface: 'enp1s0',
			rx_bytes: 0,
			tx_bytes: 0,
			rx_packets: 0,
			tx_packets: 0,
			rx_dropped: 0,
			rx_missed_errors: 0,
			link_speed_mbps: 0,
			drop_rate_pct: 0,
		});
		render(CaptureHealthPanel);
		await vi.waitFor(() => expect(screen.getByText('enp1s0')).toBeInTheDocument());
	}

	it('labels dhcp_gateway as DHCP gateway, not Inline bridge', async () => {
		await renderWithMode('dhcp_gateway');

		expect(screen.getByText('DHCP gateway')).toBeInTheDocument();
		expect(screen.queryByText('Inline bridge')).not.toBeInTheDocument();
	});

	it('still labels bridge as Inline bridge', async () => {
		await renderWithMode('bridge');
		expect(screen.getByText('Inline bridge')).toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------------
// Rendered panel: a failed request is not "Down" or a 0% drop rate (#96)
// ---------------------------------------------------------------------------

describe('CaptureHealthPanel when a request fails', () => {
	afterEach(() => {
		vi.clearAllMocks();
		vi.unstubAllGlobals();
	});

	const HEALTH = { mode: 'mirror', status: 'normal', capture_interface: 'enp4s0', link_up: true, promisc_enabled: true, issues: [] };
	const STATS = {
		capture_interface: 'enp4s0', rx_bytes: 2048, tx_bytes: 0, rx_packets: 20, tx_packets: 0,
		rx_dropped: 0, rx_missed_errors: 0, link_speed_mbps: 2500, drop_rate_pct: 0,
	};

	/** Real getters over a stubbed fetch: each URL gets its body, or HTTP 500 when it has none. */
	async function renderWith(replies: Record<string, unknown>) {
		const real = await vi.importActual<typeof import('$api/capture')>('$api/capture');
		vi.mocked(captureApi.getCaptureHealth).mockImplementation(real.getCaptureHealth);
		vi.mocked(captureApi.getCaptureStats).mockImplementation(real.getCaptureStats);
		vi.stubGlobal(
			'fetch',
			vi.fn(async (input: RequestInfo | URL) => {
				const body = replies[String(input)];
				if (body == null) return new Response('{}', { status: 500 });
				return new Response(JSON.stringify(body), { status: 200 });
			}),
		);
		render(CaptureHealthPanel);
	}

	it('says capture health could not be checked instead of "Down"', async () => {
		await renderWith({});

		expect(await screen.findByText("Couldn't check capture health: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('Down')).not.toBeInTheDocument();
		expect(screen.queryByText('Inline bridge')).not.toBeInTheDocument();
	});

	it('says the counters could not be loaded instead of a 0% drop rate', async () => {
		await renderWith({ '/api/capture/health': HEALTH });

		expect(await screen.findByText("Couldn't load capture counters: the request failed.")).toBeInTheDocument();
		expect(screen.queryByText('0.000%')).not.toBeInTheDocument();
	});

	it('shows the real readings when both requests succeed', async () => {
		await renderWith({ '/api/capture/health': HEALTH, '/api/capture/stats': STATS });

		expect(await screen.findByText('0.000%')).toBeInTheDocument();
		expect(screen.getByText('Mirror / SPAN')).toBeInTheDocument();
		expect(screen.queryByText(/Couldn't/)).not.toBeInTheDocument();
	});
});

/**
 * Tests for CaptureHealthPanel component logic.
 *
 * Extracts and tests the pure formatting/mapping functions from the component.
 */

// ---------------------------------------------------------------------------
// Reproduced pure logic from CaptureHealthPanel.svelte
// ---------------------------------------------------------------------------

function statusBadgeClass(status: string): string {
	switch (status) {
		case 'normal': return 'chip is-ok';
		case 'degraded': return 'chip is-warn';
		case 'down': return 'chip is-bad';
		case 'not_configured': return 'chip';
		default: return 'chip';
	}
}

function statusLabel(status: string): string {
	switch (status) {
		case 'normal': return 'Normal';
		case 'degraded': return 'Degraded';
		case 'down': return 'Down';
		case 'not_configured': return 'Not configured';
		default: return 'Unknown';
	}
}

function modeBadgeClass(_mode: string): string {
	return 'chip';
}

function modeLabel(mode: string): string {
	if (mode === 'dhcp_gateway') return 'DHCP gateway';
	return mode === 'mirror' ? 'Mirror / SPAN' : 'Inline bridge';
}

function formatBytes(bytes: number): string {
	if (bytes === 0) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	const value = bytes / Math.pow(1024, i);
	return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[i]}`;
}

function formatNumber(n: number): string {
	return n.toLocaleString();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CaptureHealthPanel logic', () => {
	describe('statusBadgeClass', () => {
		it('returns success for normal', () => {
			expect(statusBadgeClass('normal')).toBe('chip is-ok');
		});

		it('returns warning for degraded', () => {
			expect(statusBadgeClass('degraded')).toBe('chip is-warn');
		});

		it('returns danger for down', () => {
			expect(statusBadgeClass('down')).toBe('chip is-bad');
		});

		it('returns muted for not_configured', () => {
			expect(statusBadgeClass('not_configured')).toBe('chip');
		});

		it('returns plain chip for unknown status', () => {
			expect(statusBadgeClass('something')).toBe('chip');
		});
	});

	describe('statusLabel', () => {
		it('returns Normal for normal', () => {
			expect(statusLabel('normal')).toBe('Normal');
		});

		it('returns Degraded for degraded', () => {
			expect(statusLabel('degraded')).toBe('Degraded');
		});

		it('returns Down for down', () => {
			expect(statusLabel('down')).toBe('Down');
		});

		it('returns Not configured for not_configured', () => {
			expect(statusLabel('not_configured')).toBe('Not configured');
		});

		it('returns Unknown for unrecognized status', () => {
			expect(statusLabel('xyz')).toBe('Unknown');
		});
	});

	describe('modeBadgeClass', () => {
		it('returns a neutral chip for mirror', () => {
			expect(modeBadgeClass('mirror')).toBe('chip');
		});

		it('returns a neutral chip for bridge', () => {
			expect(modeBadgeClass('bridge')).toBe('chip');
		});

		it('returns a neutral chip for any non-mirror mode', () => {
			expect(modeBadgeClass('unknown')).toBe('chip');
		});
	});

	describe('modeLabel', () => {
		it('returns Mirror / SPAN for mirror', () => {
			expect(modeLabel('mirror')).toBe('Mirror / SPAN');
		});

		it('returns Inline bridge for bridge', () => {
			expect(modeLabel('bridge')).toBe('Inline bridge');
		});
	});

	describe('formatBytes', () => {
		it('returns 0 B for zero', () => {
			expect(formatBytes(0)).toBe('0 B');
		});

		it('formats bytes', () => {
			expect(formatBytes(500)).toBe('500 B');
		});

		it('formats KB', () => {
			expect(formatBytes(1024)).toBe('1.0 KB');
		});

		it('formats MB', () => {
			expect(formatBytes(1048576)).toBe('1.0 MB');
		});

		it('formats GB', () => {
			expect(formatBytes(1073741824)).toBe('1.0 GB');
		});

		it('formats large values without decimal', () => {
			expect(formatBytes(107374182400)).toBe('100 GB');
		});
	});

	describe('formatNumber', () => {
		it('formats numbers with locale separators', () => {
			const result = formatNumber(1234567);
			// toLocaleString output varies by locale, just check it returns a string
			expect(typeof result).toBe('string');
			expect(result.length).toBeGreaterThan(0);
		});
	});
});
