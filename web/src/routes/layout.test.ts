import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { readable } from 'svelte/store';
import * as captureApi from '$api/capture';
import Layout from './+layout.svelte';

vi.mock('$app/stores', () => ({
	page: readable({ url: new URL('http://localhost/system') }),
}));
vi.mock('$api/capture', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/capture')>()),
	getCaptureMode: vi.fn(),
}));
vi.mock('$lib/stores/captureMode', () => ({ initCaptureMode: vi.fn() }));

const children = createRawSnippet(() => ({ render: () => '<p>page body</p>' }));

describe('layout capture mode badge', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.clearAllMocks();
	});

	it.each([
		['dhcp_gateway', 'DHCP Gateway', 'mode-dhcp'],
		['mirror', 'Mirror', 'mode-mirror'],
		['bridge', 'Bridge', 'mode-bridge'],
	])('shows %s as %s', async (mode, label, cls) => {
		// NotificationBell's own requests and stream
		vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 503 })));
		vi.stubGlobal(
			'EventSource',
			class {
				addEventListener() {}
				close() {}
			}
		);
		vi.mocked(captureApi.getCaptureMode).mockResolvedValue({ mode, interface: '' });

		render(Layout, { props: { children } });

		const badge = await screen.findByTitle(`Capture mode: ${mode}`);
		expect(badge.textContent?.trim()).toBe(label);
		expect(badge).toHaveClass(cls);
	});
});

describe('layout capture mode badge when the mode request fails (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.clearAllMocks();
	});

	it('says the mode is unknown instead of guessing Bridge', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 503 })));
		vi.stubGlobal(
			'EventSource',
			class {
				addEventListener() {}
				close() {}
			}
		);
		const real = await vi.importActual<typeof import('$api/capture')>('$api/capture');
		vi.mocked(captureApi.getCaptureMode).mockImplementation(real.getCaptureMode);

		render(Layout, { props: { children } });

		expect(await screen.findByText('Mode unknown')).toBeInTheDocument();
		expect(screen.queryByText('Bridge')).not.toBeInTheDocument();
		expect(screen.getByText('page body')).toBeInTheDocument();
	});
});

// The top bar always said "Online", even with the daemon down.
describe('layout daemon status', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		vi.clearAllMocks();
	});

	/** /api/system/ping answers with `ping` (a Response, or a never-settling promise); everything else 503. */
	function stubPing(ping: () => Response | Promise<Response>): ReturnType<typeof vi.fn> {
		const fetchMock = vi.fn(async (url: string) =>
			url === '/api/system/ping' ? ping() : new Response('{}', { status: 503 }),
		);
		vi.stubGlobal('fetch', fetchMock);
		vi.stubGlobal('EventSource', class { addEventListener() {} close() {} });
		vi.mocked(captureApi.getCaptureMode).mockResolvedValue({ mode: 'bridge', interface: '' });
		return fetchMock;
	}

	const pingCalls = (f: ReturnType<typeof vi.fn>) => f.mock.calls.filter(([u]) => u === '/api/system/ping').length;

	it('says Online when the daemon answers', async () => {
		stubPing(() => new Response(JSON.stringify({ status: 'ok', uptime: 1 })));
		render(Layout, { props: { children } });
		expect(await screen.findByText('Online')).toBeInTheDocument();
	});

	it("says it can't reach NetTap when the daemon doesn't answer", async () => {
		stubPing(() => new Response(JSON.stringify({ error: 'Daemon unreachable' }), { status: 502 }));
		render(Layout, { props: { children } });
		expect(await screen.findByText("Can't reach NetTap")).toBeInTheDocument();
		expect(screen.queryByText('Online')).not.toBeInTheDocument();
	});

	it('does not take a login-page redirect for the daemon answering', async () => {
		stubPing(() => new Response('<!doctype html><title>Login</title>', { status: 200 }));
		render(Layout, { props: { children } });
		expect(await screen.findByText("Can't reach NetTap")).toBeInTheDocument();
	});

	it('says Checking… until the first answer', async () => {
		stubPing(() => new Promise<Response>(() => {}));
		render(Layout, { props: { children } });
		expect(await screen.findByText('Checking…')).toBeInTheDocument();
		expect(screen.queryByText('Online')).not.toBeInTheDocument();
	});

	it('re-checks on an interval and stops after unmount', async () => {
		vi.useFakeTimers();
		let up = true;
		const fetchMock = stubPing(() =>
			up ? new Response(JSON.stringify({ status: 'ok' })) : new Response('{}', { status: 502 }),
		);
		const { unmount } = render(Layout, { props: { children } });
		await vi.advanceTimersByTimeAsync(0);
		expect(screen.getByText('Online')).toBeInTheDocument();

		up = false;
		await vi.advanceTimersByTimeAsync(30_000);
		expect(screen.getByText("Can't reach NetTap")).toBeInTheDocument();

		const before = pingCalls(fetchMock);
		unmount();
		await vi.advanceTimersByTimeAsync(120_000);
		expect(pingCalls(fetchMock)).toBe(before);
	});
});
