import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { readable } from 'svelte/store';
import { getAlerts } from '$api/alerts';
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
