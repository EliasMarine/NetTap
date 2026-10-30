import { describe, it, expect, vi, afterEach } from 'vitest';
import { render } from '@testing-library/svelte';
import SystemPage from './+page.svelte';

/** Every request fails except /api/capture/mode; returns the list of requested URLs. */
function stubFetch(mode: string): string[] {
	const urls: string[] = [];
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: RequestInfo | URL) => {
			const url = String(input);
			urls.push(url);
			if (url === '/api/capture/mode') {
				return new Response(JSON.stringify({ mode, interface: 'enp1s0' }), { status: 200 });
			}
			return new Response(JSON.stringify({ error: 'not under test' }), { status: 503 });
		})
	);
	return urls;
}

describe('System page bridge panel', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it.each(['dhcp_gateway', 'mirror'])('hides BridgeStatus and never polls /api/bridge in %s mode', async (mode) => {
		const urls = stubFetch(mode);

		const { container } = render(SystemPage);
		await vi.waitFor(() => expect(urls).toContain('/api/capture/mode'));
		await new Promise((r) => setTimeout(r, 0));

		expect(container.querySelector('.bridge-card')).toBeNull();
		expect(urls.filter((u) => u.startsWith('/api/bridge'))).toEqual([]);
	});

	it('shows BridgeStatus and fetches bridge health in bridge mode', async () => {
		const urls = stubFetch('bridge');

		const { container } = render(SystemPage);

		await vi.waitFor(() => expect(container.querySelector('.bridge-card')).not.toBeNull());
		await vi.waitFor(() => expect(urls.some((u) => u.startsWith('/api/bridge'))).toBe(true));
	});
});
