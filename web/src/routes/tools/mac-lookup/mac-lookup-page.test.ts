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

	it('says the lookup failed instead of "Not found / Unknown vendor"', async () => {
		stubFetch(false, 500, { error: 'MAC lookup failed: OUI database unavailable' });
		await lookUp('AA:BB:CC:DD:EE:FF');

		expect(await screen.findByText('Lookup failed')).toBeInTheDocument();
		expect(screen.getByText('MAC lookup failed: OUI database unavailable')).toBeInTheDocument();
		expect(screen.queryByText('Not found')).not.toBeInTheDocument();
		expect(screen.queryByText('Unknown vendor')).not.toBeInTheDocument();
	});

	it('says "Not found" when the vendor really is not in the database', async () => {
		stubFetch(true, 200, { mac: 'AA:BB:CC:DD:EE:FF', oui_prefix: 'AA:BB:CC', vendor: '', found: false });
		await lookUp('AA:BB:CC:DD:EE:FF');

		expect(await screen.findByText('Not found')).toBeInTheDocument();
		expect(screen.getByText('Unknown vendor')).toBeInTheDocument();
		expect(screen.queryByText('Lookup failed')).not.toBeInTheDocument();
	});
});

describe('MAC lookup page states', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('starts empty', () => {
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'MAC address lookup' })).toBeInTheDocument();
		expect(screen.getByText('Enter a MAC address')).toBeInTheDocument();
	});

	it('shows the loading state while the lookup runs', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		await lookUp('AA:BB:CC:DD:EE:FF');
		expect(screen.getByRole('status')).toHaveTextContent('Looking up the vendor');
		expect(screen.getByRole('button', { name: /Looking up…/ })).toBeDisabled();
	});

	it('shows the vendor and OUI prefix when found', async () => {
		stubFetch(true, 200, { mac: 'B8:27:EB:00:00:01', oui_prefix: 'B8:27:EB', vendor: 'Raspberry Pi Foundation', found: true });
		await lookUp('b827eb000001');
		expect(await screen.findByText('Raspberry Pi Foundation')).toBeInTheDocument();
		expect(screen.getByText('B8:27:EB')).toBeInTheDocument();
		expect(screen.getByText('Found')).toBeInTheDocument();
	});
});
