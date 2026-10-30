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
