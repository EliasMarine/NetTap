import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Page from './+page.svelte';

function stubFetch(ok: boolean, status: number, body: unknown) {
	vi.stubGlobal('fetch', vi.fn(async () => ({ ok, status, json: async () => body })));
}

async function lookUp(mac: string) {
	render(Page);
	await fireEvent.input(screen.getByPlaceholderText('AA:BB:CC:DD:EE:FF'), { target: { value: mac } });
	await fireEvent.click(screen.getByRole('button', { name: /Lookup/ }));
}

describe('MAC lookup page (#96)', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('says the lookup failed instead of "Not Found / Unknown vendor"', async () => {
		stubFetch(false, 500, { error: 'MAC lookup failed: OUI database unavailable' });
		await lookUp('AA:BB:CC:DD:EE:FF');

		expect(await screen.findByText('Lookup Failed')).toBeInTheDocument();
		expect(screen.getByText('MAC lookup failed: OUI database unavailable')).toBeInTheDocument();
		expect(screen.queryByText('Not Found')).not.toBeInTheDocument();
		expect(screen.queryByText('Unknown vendor')).not.toBeInTheDocument();
	});

	it('says "Not Found" when the vendor really is not in the database', async () => {
		stubFetch(true, 200, { mac: 'AA:BB:CC:DD:EE:FF', oui_prefix: 'AA:BB:CC', vendor: '', found: false });
		await lookUp('AA:BB:CC:DD:EE:FF');

		expect(await screen.findByText('Not Found')).toBeInTheDocument();
		expect(screen.getByText('Unknown vendor')).toBeInTheDocument();
		expect(screen.queryByText('Lookup Failed')).not.toBeInTheDocument();
	});
});
