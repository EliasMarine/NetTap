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

		expect(await screen.findByText('UNIDENTIFIED')).toBeInTheDocument();
		expect(screen.getAllByText('DNS').length).toBeGreaterThan(0);
		expect(screen.queryByText('UNKNOWN')).not.toBeInTheDocument();
	});
});
