import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import IPAddress from './IPAddress.svelte';
import { expectNoNestedInteractive } from '../../tests/nested-interactive';

// NET-160: the address is a real link to where it drills down, with its menu beside it

const goto = vi.fn();
vi.mock('$app/navigation', () => ({ goto: (...a: unknown[]) => goto(...a) }));

function stubLan(subnets: string[] | null) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async () =>
			subnets
				? { ok: true, status: 200, json: async () => ({ version: subnets.join(','), subnets, source: 'env', ipv6: 'not-lan' }) }
				: { ok: false, status: 404, json: async () => ({}) },
		),
	);
}

describe('IPAddress', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		goto.mockReset();
	});

	// First: the policy store keeps the last policy it loaded for the rest of this file
	it('keeps a LAN address on the address page while the policy is unknown', async () => {
		stubLan(null);
		render(IPAddress, { ip: '192.168.1.20' });
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.getByRole('link', { name: '192.168.1.20' })).toHaveAttribute('href', '/address/192.168.1.20');
	});

	it('links an internet address to its address page', async () => {
		stubLan(['192.168.1.0/24']);
		render(IPAddress, { ip: '203.0.113.9' });
		expect(screen.getByRole('link', { name: '203.0.113.9' })).toHaveAttribute('href', '/address/203.0.113.9');
	});

	it('links a LAN address to its device page once the policy loads', async () => {
		stubLan(['192.168.1.0/24']);
		render(IPAddress, { ip: '192.168.1.20' });
		await vi.waitFor(() => expect(screen.getByRole('link', { name: '192.168.1.20' })).toHaveAttribute('href', '/devices/192.168.1.20'));
	});

	it('encodes IPv6 and never calls it LAN', async () => {
		stubLan([]);
		render(IPAddress, { ip: 'fd00::1' });
		await new Promise((r) => setTimeout(r, 0));
		expect(screen.getByRole('link', { name: 'fd00::1' })).toHaveAttribute('href', '/address/fd00%3A%3A1');
	});

	it('opens its menu beside the link, never inside it, with one connections item', async () => {
		stubLan(['192.168.1.0/24']);
		const { container } = render(IPAddress, { ip: '203.0.113.9' });
		await fireEvent.contextMenu(screen.getByRole('link', { name: '203.0.113.9' }));
		expect(screen.getByRole('menu')).toBeInTheDocument();
		expectNoNestedInteractive(container);
		expect(screen.queryByRole('menuitem', { name: /^Filter connections/ })).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('menuitem', { name: 'Connections with this address' }));
		expect(goto).toHaveBeenCalledWith('/connections?ip=203.0.113.9');
	});

	it('names the menu item after where the address goes', async () => {
		stubLan(['192.168.1.0/24']);
		render(IPAddress, { ip: '192.168.1.20' });
		await vi.waitFor(() => expect(screen.getByRole('link')).toHaveAttribute('href', '/devices/192.168.1.20'));
		await fireEvent.contextMenu(screen.getByRole('link'));
		await fireEvent.click(screen.getByRole('menuitem', { name: 'Open device page' }));
		expect(goto).toHaveBeenCalledWith('/devices/192.168.1.20');
	});

	it('renders plain text with linked={false}: no link, role, tabindex or menu', async () => {
		stubLan(['192.168.1.0/24']);
		const { container } = render(IPAddress, { ip: '203.0.113.9', linked: false });
		expect(screen.getByText('203.0.113.9')).toBeInTheDocument();
		expect(container.querySelector('a, button, [role], [tabindex]')).toBeNull();
		await fireEvent.contextMenu(screen.getByText('203.0.113.9'));
		expect(screen.queryByRole('menu')).not.toBeInTheDocument();
	});

	it('links without a menu when showMenu is false', async () => {
		stubLan(['192.168.1.0/24']);
		render(IPAddress, { ip: '203.0.113.9', showMenu: false });
		await fireEvent.contextMenu(screen.getByRole('link'));
		expect(screen.queryByRole('menu')).not.toBeInTheDocument();
	});

	describe('long press', () => {
		afterEach(() => {
			vi.useRealTimers();
			vi.restoreAllMocks();
		});
		const press = (el: Element) => {
			const event = new Event('touchstart', { bubbles: true, cancelable: true }) as TouchEvent;
			Object.defineProperty(event, 'touches', { value: [{ clientX: 10, clientY: 20 }] });
			const preventDefault = vi.spyOn(event, 'preventDefault');
			el.dispatchEvent(event);
			return preventDefault;
		};

		it('opens the menu after half a second, leaving the finished touch event alone', async () => {
			stubLan(['192.168.1.0/24']);
			vi.useFakeTimers();
			render(IPAddress, { ip: '203.0.113.9' });
			const preventDefault = press(screen.getByRole('link'));
			await vi.advanceTimersByTimeAsync(500);
			expect(screen.getByRole('menu')).toBeInTheDocument();
			expect(preventDefault).not.toHaveBeenCalled();
		});

		it("stops iOS showing Safari's link preview over the menu", async () => {
			// jsdom has no layout or iOS callout, so this reads the component's own CSS
			const source = (await import('./IPAddress.svelte?raw')).default;
			const rule = /\.ip-address\s*\{([^}]*)\}/.exec(source)?.[1] ?? '';
			expect(rule).toMatch(/-webkit-touch-callout:\s*none/);
		});

		it('drops a pending long press when the address leaves the page', async () => {
			stubLan(['192.168.1.0/24']);
			vi.useFakeTimers();
			const { unmount } = render(IPAddress, { ip: '203.0.113.9' });
			const set = vi.spyOn(globalThis, 'setTimeout');
			press(screen.getByRole('link'));
			const timer = set.mock.results.find((_, i) => set.mock.calls[i][1] === 500)?.value;
			expect(timer).toBeDefined();
			const clear = vi.spyOn(globalThis, 'clearTimeout');
			unmount();
			expect(clear).toHaveBeenCalledWith(timer);
		});
	});
});
