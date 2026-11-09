import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { createRawSnippet, tick } from 'svelte';
import type { Writable } from 'svelte/store';
import { page } from '$app/stores';
import * as captureApi from '$api/capture';
import * as systemApi from '$api/system';
import { get } from 'svelte/store';
import { _configure, alertSnapshots } from '$lib/stores/alertSnapshot';
import Layout from './+layout.svelte';

vi.mock('$app/stores', async () => {
	const { writable } = await import('svelte/store');
	return { page: writable({ url: new URL('http://localhost/system') }) };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn(), afterNavigate: vi.fn() }));
vi.mock('$api/capture', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/capture')>()),
	getCaptureMode: vi.fn(),
	getCaptureHealth: vi.fn(),
}));
vi.mock('$api/system', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/system')>()),
	getStorageStatus: vi.fn(),
}));
vi.mock('$lib/stores/captureMode', () => ({ initCaptureMode: vi.fn() }));

const children = createRawSnippet(() => ({ render: () => '<p>page body</p>' }));
const never = <T,>() => new Promise<T>(() => {});
const counts = (total: number) => ({ from: '', to: '', counts: { total, high: total, medium: 0, low: 0 } });
const pageStore = page as unknown as Writable<{ url: URL }>;

function health(status: string, iface = 'enp1s0'): captureApi.CaptureHealthResponse {
	return { mode: 'bridge', status, capture_interface: iface, link_up: true, promisc_enabled: true, issues: [] };
}

/** /api/system/ping answers with `ping`; everything else (NotificationBell's requests) 503. */
function stubFetch(ping: () => Response | Promise<Response> = () => new Response(JSON.stringify({ status: 'ok' }))) {
	const fetchMock = vi.fn(async (url: string) =>
		url === '/api/system/ping' ? ping() : new Response('{}', { status: 503 }),
	);
	vi.stubGlobal('fetch', fetchMock);
	vi.stubGlobal('EventSource', class { addEventListener() {} close() {} });
	return fetchMock;
}

function renderLayout(username: string | null = 'admin') {
	return render(Layout, { props: { children, data: { username } } });
}

beforeEach(() => {
	pageStore.set({ url: new URL('http://localhost/system') });
	_configure({ fetcher: () => never() });
	vi.mocked(captureApi.getCaptureMode).mockResolvedValue({ mode: 'bridge', interface: 'br0' });
	vi.mocked(captureApi.getCaptureHealth).mockReturnValue(never());
	vi.mocked(systemApi.getStorageStatus).mockReturnValue(never());
	stubFetch();
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.clearAllMocks();
});

describe('layout capture mode chip', () => {
	it.each([
		['dhcp_gateway', 'DHCP Gateway mode · eth1'],
		['mirror', 'Mirror mode · eth1'],
		['bridge', 'Bridge mode · eth1'],
	])('shows %s as "%s" while capture is healthy', async (mode, text) => {
		vi.mocked(captureApi.getCaptureMode).mockResolvedValue({ mode, interface: 'eth1' });
		vi.mocked(captureApi.getCaptureHealth).mockResolvedValue(health('normal', 'eth1'));
		renderLayout();
		expect(await screen.findByText(text)).toBeInTheDocument();
	});

	it('says the mode is unknown instead of guessing Bridge (#96)', async () => {
		vi.mocked(captureApi.getCaptureMode).mockRejectedValue(new Error('503'));
		renderLayout();
		expect(await screen.findByText('Mode unknown')).toBeInTheDocument();
		expect(screen.queryByText(/Bridge/)).not.toBeInTheDocument();
		expect(screen.getByText('page body')).toBeInTheDocument();
	});

	it('still shows capture health when the mode request fails', async () => {
		vi.mocked(captureApi.getCaptureMode).mockRejectedValue(new Error('503'));
		vi.mocked(captureApi.getCaptureHealth).mockResolvedValue(health('down'));
		renderLayout();
		expect(await screen.findByText('Capture stopped')).toBeInTheDocument();
	});

	it('says capture status is unknown when the health request fails', async () => {
		vi.mocked(captureApi.getCaptureHealth).mockRejectedValue(new Error('503'));
		renderLayout();
		expect(await screen.findByText('Capture status unknown')).toBeInTheDocument();
	});
});

// The top bar used to say "Online" even with the daemon down.
describe('layout daemon status', () => {
	const pingCalls = (f: ReturnType<typeof vi.fn>) => f.mock.calls.filter(([u]) => u === '/api/system/ping').length;

	it('shows no warning while the daemon answers', async () => {
		const f = stubFetch();
		renderLayout();
		await vi.waitFor(() => expect(pingCalls(f)).toBe(1));
		await tick();
		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
	});

	it("warns that it can't reach NetTap when the daemon doesn't answer", async () => {
		stubFetch(() => new Response(JSON.stringify({ error: 'Daemon unreachable' }), { status: 502 }));
		renderLayout();
		expect(await screen.findByText("Can't reach NetTap")).toBeInTheDocument();
	});

	it('does not take a login-page redirect for the daemon answering', async () => {
		stubFetch(() => new Response('<!doctype html><title>Login</title>', { status: 200 }));
		renderLayout();
		expect(await screen.findByText("Can't reach NetTap")).toBeInTheDocument();
	});

	it('does not warn before the first answer', async () => {
		stubFetch(() => never());
		renderLayout();
		await tick();
		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();
	});

	it('re-checks every 30 s with capture health and storage, and stops after unmount', async () => {
		vi.useFakeTimers();
		let up = true;
		const f = stubFetch(() => (up ? new Response(JSON.stringify({ status: 'ok' })) : new Response('{}', { status: 502 })));
		const { unmount } = renderLayout();
		await vi.advanceTimersByTimeAsync(0);
		expect(screen.queryByText("Can't reach NetTap")).not.toBeInTheDocument();

		up = false;
		await vi.advanceTimersByTimeAsync(30_000);
		expect(screen.getByText("Can't reach NetTap")).toBeInTheDocument();
		expect(captureApi.getCaptureHealth).toHaveBeenCalledTimes(2);
		expect(systemApi.getStorageStatus).toHaveBeenCalledTimes(2);

		const before = pingCalls(f);
		unmount();
		await vi.advanceTimersByTimeAsync(120_000);
		expect(pingCalls(f)).toBe(before);
	});

	it('pauses polling while the tab is hidden', async () => {
		vi.useFakeTimers();
		const f = stubFetch();
		renderLayout();
		await vi.advanceTimersByTimeAsync(0);
		const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
		await vi.advanceTimersByTimeAsync(90_000);
		expect(pingCalls(f)).toBe(1);
		hidden.mockRestore();
	});
});

describe('layout sidebar', () => {
	it('marks the current page, including nested routes', async () => {
		pageStore.set({ url: new URL('http://localhost/devices/10.0.0.5') });
		renderLayout();
		const nav = screen.getByRole('navigation', { name: 'Main' });
		expect(within(nav).getByRole('link', { name: /^Devices/ })).toHaveAttribute('aria-current', 'page');
		expect(within(nav).getByRole('link', { name: /^Home/ })).not.toHaveAttribute('aria-current');
	});

	// OLD CODE START — NET-160: 17 links before Investigations and Security posture joined
	// it('keeps all 17 page links', () => { … expect(new Set(hrefs).size).toBe(17); });
	// OLD CODE END
	// OLD CODE START — NET-188: 19 links before Packet analysis joined
	// it('keeps all 19 page links', () => { … expect(new Set(hrefs).size).toBe(19); … });
	// OLD CODE END
	it('keeps all 20 page links', () => {
		renderLayout();
		const nav = screen.getByRole('navigation', { name: 'Main' });
		// the brand link also points home, so 21 links share 20 hrefs
		const hrefs = within(nav).getAllByRole('link').map((a) => a.getAttribute('href'));
		expect(new Set(hrefs).size).toBe(20);
		expect(hrefs).toEqual(expect.arrayContaining(['/investigations', '/compliance', '/packets']));
	});

	it('shows the storage used and free space', async () => {
		vi.mocked(systemApi.getStorageStatus).mockResolvedValue({
			disk_usage_percent: 41.2,
			disk_total_bytes: 1e12,
			disk_used_bytes: 4.12e11,
			disk_free_bytes: 5.88e11,
			retention: { hot_days: 90 },
		} as systemApi.StorageStatus);
		renderLayout();
		expect(await screen.findByText('41% used')).toBeInTheDocument();
		expect(screen.getByText(/90-day retention/)).toBeInTheDocument();
		expect(screen.getByRole('meter', { name: 'Disk used' })).toHaveAttribute('aria-valuenow', '41');
	});

	it('hides storage when its request fails', async () => {
		vi.mocked(systemApi.getStorageStatus).mockRejectedValue(new Error('503'));
		renderLayout();
		await tick();
		await tick();
		expect(screen.queryByText(/% used/)).not.toBeInTheDocument();
	});

	it('shows the signed-in user and a sign-out button inside the logout form', () => {
		renderLayout('admin');
		expect(screen.getByText('admin')).toBeInTheDocument();
		const button = screen.getByRole('button', { name: 'Sign out' });
		const form = button.closest('form');
		expect(form).toHaveAttribute('method', 'POST');
		expect(form).toHaveAttribute('action', '/api/auth/logout');
		expect(button).toHaveAttribute('type', 'submit');
	});

	// NET-228 (audit HON-49): a failed count showed no badge, the same as zero
	it.each([
		['a failed count', () => Promise.reject(new Error('503')), '?', "Couldn't load the alert count"],
		['a count', () => Promise.resolve(counts(7)), '7', '7 alerts in the last 24 hours'],
	])('badges %s on Alerts', async (_what, fetcher, badge, spoken) => {
		_configure({ fetcher: fetcher as never });
		renderLayout();
		const alerts = within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: /^Alerts/ });
		await vi.waitFor(() => expect(within(alerts).getByText(spoken)).toBeInTheDocument());
		expect(within(alerts).getByText(badge)).toHaveClass('count');
	});

	it('shows no badge for zero alerts', async () => {
		_configure({ fetcher: (() => Promise.resolve(counts(0))) as never });
		renderLayout();
		await vi.waitFor(() => expect(get(alertSnapshots)[24]?.status).toBe('ok'));
		await tick();
		const alerts = within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: /^Alerts/ });
		expect(alerts.querySelector('.count')).toBeNull();
	});

	it('hides the user row without a username but keeps sign-out', () => {
		renderLayout(null);
		expect(screen.queryByText('admin')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
	});
});

describe('layout phone menu', () => {
	function openMenu() {
		const button = screen.getByRole('button', { name: 'Open menu' });
		return { button, done: fireEvent.click(button) };
	}

	it('opens the drawer and moves focus to the first link', async () => {
		const { container } = renderLayout();
		const { button, done } = openMenu();
		await done;
		await tick();
		expect(button).toHaveAttribute('aria-expanded', 'true');
		expect(button).toHaveAttribute('aria-controls', 'app-sidebar');
		expect(container.querySelector('.app')).toHaveClass('nav-open');
		const nav = screen.getByRole('navigation', { name: 'Main' });
		expect(nav.contains(document.activeElement)).toBe(true);
	});

	it('closes on Escape and returns focus to the menu button', async () => {
		const { container } = renderLayout();
		const { button, done } = openMenu();
		await done;
		await tick();
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(container.querySelector('.app')).not.toHaveClass('nav-open');
		expect(button).toHaveAttribute('aria-expanded', 'false');
		expect(document.activeElement).toBe(button);
	});

	it('closes when the scrim is clicked', async () => {
		const { container } = renderLayout();
		await openMenu().done;
		await fireEvent.click(screen.getByRole('button', { name: 'Close menu' }));
		expect(container.querySelector('.app')).not.toHaveClass('nav-open');
	});

	it('closes when a link is chosen', async () => {
		const { container } = renderLayout();
		await openMenu().done;
		const nav = screen.getByRole('navigation', { name: 'Main' });
		const link = within(nav).getByRole('link', { name: /^Alerts/ });
		link.addEventListener('click', (e) => e.preventDefault()); // jsdom can't navigate
		await fireEvent.click(link);
		expect(container.querySelector('.app')).not.toHaveClass('nav-open');
	});

	it('keeps Tab inside the open drawer', async () => {
		renderLayout();
		await openMenu().done;
		await tick();
		const nav = screen.getByRole('navigation', { name: 'Main' });
		const items = [...nav.querySelectorAll<HTMLElement>('a[href], button:not([disabled])')];
		items[items.length - 1].focus();
		await fireEvent.keyDown(window, { key: 'Tab' });
		expect(document.activeElement).toBe(items[0]);
		await fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
		expect(document.activeElement).toBe(items[items.length - 1]);
	});
});

describe('layout without the shell', () => {
	it.each(['/login', '/setup'])('renders %s bare', (path) => {
		pageStore.set({ url: new URL(`http://localhost${path}`) });
		renderLayout(null);
		expect(screen.getByText('page body')).toBeInTheDocument();
		expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
		expect(captureApi.getCaptureHealth).not.toHaveBeenCalled();
	});
});
