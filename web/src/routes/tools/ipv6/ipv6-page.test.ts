import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import Page from './+page.svelte';
import { expectNoNestedInteractive } from '../../../tests/nested-interactive';
import type { MacLookupResult } from '$api/tools';

const { pageUrl } = vi.hoisted(() => ({ pageUrl: { current: new URL('http://localhost/tools/ipv6') } }));

vi.mock('$app/navigation', () => ({ replaceState: vi.fn() }));
vi.mock('$app/stores', async () => {
	const { readable } = await import('svelte/store');
	return { page: readable({ get url() { return pageUrl.current; } }) };
});
vi.mock('$api/tools', () => ({ macLookup: vi.fn() }));

const { replaceState } = await import('$app/navigation');
const { macLookup } = await import('$api/tools');
const lookup = vi.mocked(macLookup);

const LOOKUP_DELAY_MS = 400;
const EUI_A = 'fe80::a00:27ff:fe4e:66a1'; // candidate MAC 08:00:27:4e:66:a1
const EUI_B = 'fe80::ba27:ebff:fe12:3456'; // candidate MAC b8:27:eb:12:34:56

const vendor = (mac: string, name: string): MacLookupResult => ({ mac, oui_prefix: mac.slice(0, 8), vendor: name, found: true });
const field = () => screen.getByLabelText('IPv6 address');
const type = (value: string) => fireEvent.input(field(), { target: { value } });
const fact = (label: string) => screen.getByText(label, { selector: 'dt' }).nextElementSibling;

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

/** Lets the debounce fire and any resolved lookup reach the page */
async function settle(ms = LOOKUP_DELAY_MS) {
	await vi.advanceTimersByTimeAsync(ms);
	await tick();
}

beforeEach(() => {
	pageUrl.current = new URL('http://localhost/tools/ipv6');
	// The LAN policy store asks the daemon on subscribe; it isn't needed here
	vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })));
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.clearAllMocks();
});

describe('IPv6 toolkit page', () => {
	it('starts empty and explains an example when it is chosen', async () => {
		const { container } = render(Page);
		expect(screen.getByRole('heading', { level: 1, name: 'IPv6 toolkit' })).toBeInTheDocument();
		expect(screen.getByText('Enter an IPv6 address')).toBeInTheDocument();

		await fireEvent.click(screen.getByRole('button', { name: 'IPv4-mapped' }));
		expect(field()).toHaveValue('::ffff:192.0.2.10');
		expect(fact('Embedded IPv4')).toHaveTextContent('192.0.2.10');
		expect(String(vi.mocked(replaceState).mock.calls.at(-1)?.[0])).toBe('http://localhost:3000/?address=%3A%3Affff%3A192.0.2.10');
		expectNoNestedInteractive(container);
	});

	it('keeps what is typed in the URL, so the link can be shared', async () => {
		render(Page);
		await type('fe80::1');
		expect(String(vi.mocked(replaceState).mock.calls.at(-1)?.[0])).toBe('http://localhost:3000/?address=fe80%3A%3A1');
		await type('');
		expect(String(vi.mocked(replaceState).mock.calls.at(-1)?.[0])).toBe('http://localhost:3000/');
	});

	it('reads a shared address from the URL', () => {
		pageUrl.current = new URL('http://localhost/tools/ipv6?address=2001:db8::1234');
		render(Page);
		expect(screen.getByText('Documentation', { selector: '.chip' })).toBeInTheDocument();
		expect(fact('Full form')).toHaveTextContent('2001:0db8:0000:0000:0000:0000:0000:1234');
	});

	it('says what is wrong, and sends IPv4 to the Subnet calculator', async () => {
		render(Page);
		await type('2001:db8::g1');
		expect(screen.getByRole('alert')).toHaveTextContent('"g1" isn\'t hex');
		await type('192.168.1.10');
		expect(screen.getByRole('link', { name: 'Open the Subnet calculator' })).toHaveAttribute('href', '/tools/subnet-calc');
	});

	it('reads a network in CIDR as a network, with no device part', async () => {
		render(Page);
		await type('2001:db8:abcd:1200::/56');
		expect(fact('Networks of /64')).toHaveTextContent('256');
		expect(screen.getByText('No device part')).toBeInTheDocument();
	});

	it('keeps the ranges table collapsed until asked', () => {
		const { container } = render(Page);
		const details = container.querySelector('details.ranges');
		expect(details).not.toHaveAttribute('open');
		expect(screen.getByText('Show the 10 ranges')).toBeInTheDocument();
	});

	it('builds an address from a MAC and explains it', async () => {
		render(Page);
		await fireEvent.input(screen.getByLabelText('MAC address'), { target: { value: 'b8:27:eb:12:34:56' } });
		await fireEvent.input(screen.getByLabelText('Network prefix (optional)'), { target: { value: '2001:db8:1:2::/64' } });
		expect(fact('IPv6 address')).toHaveTextContent('2001:db8:1:2:ba27:ebff:fe12:3456');
		await fireEvent.click(screen.getByRole('button', { name: 'Explain this address' }));
		expect(field()).toHaveValue('2001:db8:1:2:ba27:ebff:fe12:3456');
		await fireEvent.input(screen.getByLabelText('Network prefix (optional)'), { target: { value: 'ff02::/64' } });
		expect(screen.getByRole('alert')).toHaveTextContent("Multicast addresses aren't built with SLAAC");
	});
});

describe('copy buttons', () => {
	const writeText = vi.fn();
	beforeEach(() => {
		Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
	});

	it('copies the value and confirms it', async () => {
		writeText.mockResolvedValue(undefined);
		pageUrl.current = new URL('http://localhost/tools/ipv6?address=2001:DB8:0:0:0:0:0:1');
		render(Page);
		await fireEvent.click(screen.getByRole('button', { name: 'Copy short form' }));
		await tick();
		expect(writeText).toHaveBeenCalledWith('2001:db8::1');
		expect(screen.getByText('Copied short form')).toBeInTheDocument();
	});

	it("says when the browser won't copy", async () => {
		writeText.mockRejectedValue(new Error('denied'));
		pageUrl.current = new URL('http://localhost/tools/ipv6?address=2001:db8::1');
		render(Page);
		await fireEvent.click(screen.getByRole('button', { name: 'Copy full form' }));
		await tick();
		expect(screen.getByText("Couldn't copy")).toBeInTheDocument();
	});
});

describe('maker of the candidate MAC', () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	it('looks it up once, after the debounce, and names it as the maker of that MAC', async () => {
		lookup.mockResolvedValue(vendor('08:00:27:4e:66:a1', 'PCS Systemtechnik GmbH'));
		render(Page);
		await type(EUI_A);
		expect(fact('Maker of that MAC')).toHaveTextContent('Looking up…');
		expect(lookup).not.toHaveBeenCalled();
		await settle();
		expect(lookup).toHaveBeenCalledExactlyOnceWith('08:00:27:4e:66:a1');
		expect(fact('Maker of that MAC')).toHaveTextContent('PCS Systemtechnik GmbH');
	});

	it('collapses fast typing into one lookup', async () => {
		lookup.mockResolvedValue(vendor('08:00:27:4e:66:a1', 'PCS Systemtechnik GmbH'));
		render(Page);
		await type(EUI_A);
		await settle(200);
		await type(EUI_B);
		await settle(200);
		await type(EUI_A);
		await settle();
		expect(lookup).toHaveBeenCalledExactlyOnceWith('08:00:27:4e:66:a1');
	});

	it('shows a failed lookup as an error', async () => {
		lookup.mockRejectedValue(new Error('MAC lookup failed: HTTP 502'));
		render(Page);
		await type(EUI_A);
		await settle();
		expect(fact('Maker of that MAC')).toHaveTextContent("Couldn't look up the maker: MAC lookup failed: HTTP 502");
	});

	it('never lets an older reply overwrite a newer one (A → B → A, replies out of order)', async () => {
		const a1 = deferred<MacLookupResult>();
		const b = deferred<MacLookupResult>();
		const a2 = deferred<MacLookupResult>();
		lookup.mockImplementationOnce(() => a1.promise).mockImplementationOnce(() => b.promise).mockImplementationOnce(() => a2.promise);
		render(Page);
		await type(EUI_A);
		await settle();
		await type(EUI_B);
		await settle();
		await type(EUI_A);
		await settle();
		expect(lookup).toHaveBeenCalledTimes(3);

		a2.resolve(vendor('08:00:27:4e:66:a1', 'Newest answer'));
		await settle(0);
		a1.reject(new Error('late failure'));
		b.resolve(vendor('b8:27:eb:12:34:56', 'Stale answer'));
		await settle(0);
		expect(fact('Maker of that MAC')).toHaveTextContent('Newest answer');
		expect(screen.queryByText(/late failure|Stale answer/)).not.toBeInTheDocument();
	});

	it('skips the lookup for a locally administered MAC', async () => {
		render(Page);
		await type('fe80::ff:fe00:1');
		await settle();
		expect(lookup).not.toHaveBeenCalled();
		expect(fact('Maker of that MAC')).toHaveTextContent('A locally administered MAC has no maker.');
	});
});
