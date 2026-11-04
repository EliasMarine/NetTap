import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import Page from './+page.svelte';

const search = vi.hoisted(() => ({ value: '' }));
// Each subscriber reads the query string the current test set
vi.mock('$app/stores', () => ({
	page: {
		subscribe(run: (value: unknown) => void) {
			run({ url: new URL(`http://localhost/tools/ssl-cert${search.value}`), params: {} });
			return () => {};
		},
	},
}));

const DAY = 86_400_000;
const cert = (notAfterMs: number) => ({
	host: 'example.com',
	port: 443,
	subject: { CN: 'example.com' },
	issuer: { CN: 'Example CA' },
	not_before: new Date(Date.now() - 30 * DAY).toISOString(),
	not_after: new Date(Date.now() + notAfterMs).toISOString(),
	serial: '0A1B2C',
	fingerprint_sha256: 'AB:CD:EF',
	san: ['example.com', 'www.example.com'],
	chain: ['CN=example.com', 'CN=Example CA'],
	raw: 'Certificate:\n  Data: …',
});

function stubFetch(body: unknown, ok = true) {
	vi.stubGlobal('fetch', vi.fn(async () => ({ ok, status: ok ? 200 : 502, json: async () => body })));
}

async function inspect() {
	await fireEvent.input(screen.getByLabelText('Host'), { target: { value: 'example.com' } });
	await fireEvent.click(screen.getByRole('button', { name: 'Inspect' }));
}

describe('SSL certificate viewer page', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		search.value = '';
	});

	it('starts empty and reads ?host on load', () => {
		search.value = '?host=nettap.local';
		render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'SSL certificate viewer' })).toBeInTheDocument();
		expect(screen.getByLabelText('Host')).toHaveValue('nettap.local');
		expect(screen.getByText('Enter a host')).toBeInTheDocument();
	});

	it('shows the loading state while the inspection runs', async () => {
		vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
		render(Page);
		await inspect();
		expect(screen.getByRole('status')).toHaveTextContent('Inspecting the certificate');
	});

	it('shows the certificate facts, names, chain and the validity chip', async () => {
		stubFetch(cert(90 * DAY));
		render(Page);
		await inspect();
		expect(await screen.findByText('example.com:443')).toBeInTheDocument();
		expect(screen.getByText('Example CA')).toBeInTheDocument();
		expect(screen.getByText('www.example.com')).toBeInTheDocument();
		expect(screen.getByText('CN=Example CA')).toBeInTheDocument();
		expect(screen.getByText(/^Valid \(\d+d remaining\)$/)).toHaveClass('chip', 'is-ok');

		await fireEvent.click(screen.getByRole('button', { name: 'Show raw certificate output' }));
		expect(screen.getByText(/Certificate:/)).toBeInTheDocument();
	});

	it('marks an expired certificate', async () => {
		stubFetch(cert(-3 * DAY));
		render(Page);
		await inspect();
		expect(await screen.findByText(/^Expired \d+d ago$/)).toHaveClass('chip', 'is-bad');
	});

	it('shows the error state with the daemon message when the inspection fails', async () => {
		stubFetch({ error: 'Connection refused' }, false);
		render(Page);
		await inspect();
		expect(await screen.findByText('Inspection failed')).toBeInTheDocument();
		expect(screen.getByText('Connection refused')).toBeInTheDocument();
	});
});
