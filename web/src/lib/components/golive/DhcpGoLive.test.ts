import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import * as dhcpApi from '$api/dhcpGateway';
import type { DhcpCheck, DhcpPreflight, DhcpStatus } from '$api/dhcpGateway';
import DhcpGoLive from './DhcpGoLive.svelte';

vi.mock('$api/dhcpGateway', async (importOriginal) => ({
	...(await importOriginal<typeof import('$api/dhcpGateway')>()),
	getDhcpPreflight: vi.fn(),
	getDhcpStatus: vi.fn(),
	enableDhcpGateway: vi.fn(),
	disableDhcpGateway: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const UPSTREAM = { address: '192.168.1.50/24', gateway: '192.168.1.1' };

function check(name: string, passed: boolean, message = '', blocking = true): DhcpCheck {
	return { name, passed, blocking, message };
}

const PASSING_CHECKS = [
	check('interface_up', true),
	check('upstream_detected', true),
	check('no_other_dhcp', true),
	check('no_subnet_conflict', true),
	check('ip_forward', true),
	check('firewall_backend', true),
	check('ipv6_bypass', true, '', false),
];

function preflight(overrides: Partial<DhcpPreflight> = {}): DhcpPreflight {
	return {
		interface: 'enp1s0',
		subnet: '10.77.0.0/24',
		gateway_ip: '10.77.0.1',
		upstream: UPSTREAM,
		subnet_conflicts: [],
		other_dhcp_servers: [],
		ipv6_router_advertisements: false,
		ip_forward: true,
		firewall_backend: 'iptables-nft',
		checks: PASSING_CHECKS,
		ready: true,
		...overrides,
	};
}

const BLOCKED = preflight({
	ready: false,
	other_dhcp_servers: [{ server_ip: '192.168.1.1', offered_ip: '192.168.1.77' }],
	checks: [
		check('interface_up', true),
		check('no_other_dhcp', false, "Your router's DHCP server is still on (192.168.1.1)."),
	],
});

function status(overrides: Partial<DhcpStatus> = {}): DhcpStatus {
	return {
		interface: 'enp1s0',
		subnet: '10.77.0.0/24',
		gateway_ip: '10.77.0.1',
		upstream: UPSTREAM,
		routing_active: true,
		dhcp_enabled: true,
		dhcp_server_running: true,
		leases: [],
		issues: [],
		...overrides,
	};
}

const NOT_ENABLED = status({ routing_active: false, dhcp_enabled: false, dhcp_server_running: false });

const LEASES = [
	{ mac: 'aa:aa:aa:aa:aa:03', ip: '10.77.0.100', hostname: 'tv', expires: 2_000_000_300 },
	{ mac: 'aa:aa:aa:aa:aa:01', ip: '10.77.0.23', hostname: 'pixel-8', expires: 2_000_000_100 },
	{ mac: 'aa:aa:aa:aa:aa:02', ip: '10.77.0.9', hostname: 'laptop', expires: 2_000_000_200 },
];

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

function rowCells(column: number): string[] {
	return screen
		.getAllByRole('row')
		.slice(1)
		.map((row) => row.querySelectorAll('td')[column].textContent ?? '');
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DhcpGoLive', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.clearAllMocks();
	});

	it('shows a loading state while checking', () => {
		vi.mocked(dhcpApi.getDhcpStatus).mockReturnValue(new Promise(() => {}));

		render(DhcpGoLive);

		expect(screen.getByText(/Checking your network/)).toBeInTheDocument();
	});

	it('shows the error with a working Retry', async () => {
		vi.mocked(dhcpApi.getDhcpStatus).mockRejectedValueOnce(new Error('Capture mode is not dhcp_gateway'));

		render(DhcpGoLive);
		await flush();

		expect(screen.getByText(/Capture mode is not dhcp_gateway/)).toBeInTheDocument();

		vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(NOT_ENABLED);
		vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValue(preflight());
		await fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
		await flush();

		expect(dhcpApi.getDhcpStatus).toHaveBeenCalledTimes(2);
		expect(screen.getByText('Turn on the DHCP gateway')).toBeInTheDocument();
	});

	describe('blocked', () => {
		it('shows failed check messages and router DHCP steps, and re-checks', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(NOT_ENABLED);
			vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValueOnce(BLOCKED);

			render(DhcpGoLive);
			await flush();

			expect(screen.getByText("Your router's DHCP server is still on (192.168.1.1).")).toBeInTheDocument();
			expect(screen.getByText("Turn off your router's DHCP server")).toBeInTheDocument();
			expect(screen.getByText('http://192.168.1.1')).toBeInTheDocument();
			expect(screen.getByText(/look for the setting in the app/)).toBeInTheDocument();
			// No dead end into Setup: the wizard can't save after first run
			expect(screen.getByText(/switching modes after setup isn't available in the app yet/)).toBeInTheDocument();
			expect(document.querySelector('a[href="/setup"]')).toBeNull();
			expect(screen.queryByRole('button', { name: 'Enable DHCP gateway' })).not.toBeInTheDocument();

			vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValueOnce(preflight());
			await fireEvent.click(screen.getByRole('button', { name: 'Check again' }));
			await flush();

			expect(dhcpApi.getDhcpPreflight).toHaveBeenCalledTimes(2);
			expect(screen.getByRole('button', { name: 'Enable DHCP gateway' })).toBeInTheDocument();
		});

		it('does not show the router steps when a different check fails', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(NOT_ENABLED);
			vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValue(
				preflight({ ready: false, checks: [check('ip_forward', false, 'IP forwarding is off on the host.')] }),
			);

			render(DhcpGoLive);
			await flush();

			expect(screen.getByText('IP forwarding is off on the host.')).toBeInTheDocument();
			expect(screen.queryByText("Turn off your router's DHCP server")).not.toBeInTheDocument();
			expect(screen.getByText('Fix the problems above first')).toBeInTheDocument();
			expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument();
		});

		it('says to fix other blocking checks first, not to touch the router, even when its DHCP is on', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(NOT_ENABLED);
			vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValue(
				preflight({
					ready: false,
					other_dhcp_servers: [{ server_ip: '192.168.1.1', offered_ip: '192.168.1.77' }],
					checks: [
						check('no_other_dhcp', false, "Your router's DHCP server is still on (192.168.1.1)."),
						check('firewall_backend', false, "Docker's DOCKER-USER firewall chain was not found."),
					],
				}),
			);

			render(DhcpGoLive);
			await flush();

			expect(screen.getByText('Fix the problems above first')).toBeInTheDocument();
			expect(screen.getByText(/Don't turn off its DHCP server yet/)).toBeInTheDocument();
			expect(screen.queryByText("Turn off your router's DHCP server")).not.toBeInTheDocument();
		});

		it('reports a failed DHCP probe as a probe error, not as the router DHCP being on', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(NOT_ENABLED);
			vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValue(
				preflight({
					ready: false,
					other_dhcp_servers: [],
					checks: [
						check('interface_up', true),
						check('no_other_dhcp', false, 'NetTap could not check for other DHCP servers: Operation not permitted'),
					],
				}),
			);

			render(DhcpGoLive);
			await flush();

			expect(screen.getByText("NetTap couldn't check for other DHCP servers")).toBeInTheDocument();
			expect(screen.getByText('Check for other DHCP servers')).toBeInTheDocument();
			expect(screen.queryByText("Router's DHCP server is off")).not.toBeInTheDocument();
			expect(screen.queryByText("Turn off your router's DHCP server")).not.toBeInTheDocument();
			expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument();
		});
	});

	describe('ready', () => {
		async function renderReady() {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(NOT_ENABLED);
			vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValue(preflight());
			render(DhcpGoLive);
			await flush();
		}

		it('says devices move over when their router address runs out', async () => {
			await renderReady();

			expect(screen.getByText(/runs out \(often up to a day\)/)).toBeInTheDocument();
			expect(screen.queryByText(/30 minutes/)).not.toBeInTheDocument();
		});

		it('keeps Enable disabled until the confirmation is checked', async () => {
			await renderReady();

			const enable = screen.getByRole('button', { name: 'Enable DHCP gateway' });
			expect(enable).toBeDisabled();
			await fireEvent.click(enable);
			expect(dhcpApi.enableDhcpGateway).not.toHaveBeenCalled();

			const box = screen.getByRole('checkbox', { name: /NetTap becomes my network's gateway/ });
			expect(screen.getByText(/lose internet/)).toBeInTheDocument();
			await fireEvent.click(box);

			expect(enable).toBeEnabled();
		});

		it('enables and switches to the live status', async () => {
			await renderReady();
			vi.mocked(dhcpApi.enableDhcpGateway).mockResolvedValue(status());

			await fireEvent.click(screen.getByRole('checkbox'));
			await fireEvent.click(screen.getByRole('button', { name: 'Enable DHCP gateway' }));
			await flush();

			expect(dhcpApi.enableDhcpGateway).toHaveBeenCalledTimes(1);
			expect(screen.getByText("NetTap is now your network's gateway.")).toBeInTheDocument();
		});

		it('goes back to blocked with a fresh preflight on a 409', async () => {
			await renderReady();
			vi.mocked(dhcpApi.enableDhcpGateway).mockRejectedValue(
				new dhcpApi.DhcpGatewayError('Preflight failed', 409, [
					check('no_other_dhcp', false, 'Another DHCP server answered (192.168.1.1).'),
				]),
			);
			vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValueOnce(BLOCKED);

			await fireEvent.click(screen.getByRole('checkbox'));
			await fireEvent.click(screen.getByRole('button', { name: 'Enable DHCP gateway' }));
			await flush();

			expect(dhcpApi.getDhcpPreflight).toHaveBeenCalledTimes(2);
			expect(screen.getByText('Preflight failed')).toBeInTheDocument();
			expect(screen.getByText("Your router's DHCP server is still on (192.168.1.1).")).toBeInTheDocument();
			// The fresh preflight lists the router as answering, so the router guide shows
			expect(screen.getByText("Turn off your router's DHCP server")).toBeInTheDocument();
			expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument();
			expect(screen.queryByRole('button', { name: 'Enable DHCP gateway' })).not.toBeInTheDocument();
		});

		it('falls back to the 409 checks when the fresh preflight fails', async () => {
			await renderReady();
			vi.mocked(dhcpApi.enableDhcpGateway).mockRejectedValue(
				new dhcpApi.DhcpGatewayError('Preflight failed', 409, [
					check('ip_forward', false, 'IP forwarding is off on this machine.'),
				]),
			);
			vi.mocked(dhcpApi.getDhcpPreflight).mockRejectedValueOnce(new Error('HTTP 502'));

			await fireEvent.click(screen.getByRole('checkbox'));
			await fireEvent.click(screen.getByRole('button', { name: 'Enable DHCP gateway' }));
			await flush();

			expect(screen.getByText('IP forwarding is off on this machine.')).toBeInTheDocument();
			expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument();
		});

		it('shows the enabled view with a note when enable errors but the status says it is on', async () => {
			await renderReady();
			vi.mocked(dhcpApi.enableDhcpGateway).mockRejectedValue(
				new dhcpApi.DhcpGatewayError('Daemon unreachable: The operation was aborted due to timeout', 502),
			);
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(status());

			await fireEvent.click(screen.getByRole('checkbox'));
			await fireEvent.click(screen.getByRole('button', { name: 'Enable DHCP gateway' }));
			await flush();

			expect(dhcpApi.getDhcpStatus).toHaveBeenCalledTimes(2);
			expect(screen.getByText("NetTap is now your network's gateway.")).toBeInTheDocument();
			expect(screen.getByText(/took longer than expected/)).toBeInTheDocument();
			expect(screen.queryByText(/aborted due to timeout/)).not.toBeInTheDocument();
		});

		it('keeps the error when only routing is on after a failed re-enable', async () => {
			// enable -> disable -> re-enable where dnsmasq fails: the daemon rolls
			// back to routing on, DHCP server off. That is a failure, not success.
			await renderReady();
			vi.mocked(dhcpApi.enableDhcpGateway).mockRejectedValue(
				new dhcpApi.DhcpGatewayError('dnsmasq exited: failed to bind DHCP server socket', 500),
			);
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(status({ dhcp_enabled: false, routing_active: true }));

			await fireEvent.click(screen.getByRole('checkbox'));
			await fireEvent.click(screen.getByRole('button', { name: 'Enable DHCP gateway' }));
			await flush();

			expect(screen.queryByText(/took longer than expected/)).not.toBeInTheDocument();
			expect(screen.queryByText("NetTap is now your network's gateway.")).not.toBeInTheDocument();
			expect(screen.getByText(/failed to bind DHCP server socket/)).toBeInTheDocument();
		});

		it('shows capture restart errors from the enable response as a warning', async () => {
			await renderReady();
			vi.mocked(dhcpApi.enableDhcpGateway).mockResolvedValue({
				...status(),
				capture_restart: { restarted: ['nettap-zeek'], errors: ['nettap-arkime: restart timed out'] },
			});

			await fireEvent.click(screen.getByRole('checkbox'));
			await fireEvent.click(screen.getByRole('button', { name: 'Enable DHCP gateway' }));
			await flush();

			expect(
				screen.getByText('Capture is still on the old settings: nettap-arkime: restart timed out'),
			).toBeInTheDocument();
		});

		it('has no capture warning when the restart went through', async () => {
			await renderReady();
			vi.mocked(dhcpApi.enableDhcpGateway).mockResolvedValue({
				...status(),
				capture_restart: { restarted: ['nettap-zeek'], errors: [] },
			});

			await fireEvent.click(screen.getByRole('checkbox'));
			await fireEvent.click(screen.getByRole('button', { name: 'Enable DHCP gateway' }));
			await flush();

			expect(screen.queryByText(/Capture is still on the old settings/)).not.toBeInTheDocument();
		});

		it('stays ready and shows the error when enabling fails', async () => {
			await renderReady();
			vi.mocked(dhcpApi.enableDhcpGateway).mockRejectedValue(new dhcpApi.DhcpGatewayError('Apply failed', 500));

			await fireEvent.click(screen.getByRole('checkbox'));
			await fireEvent.click(screen.getByRole('button', { name: 'Enable DHCP gateway' }));
			await flush();

			expect(screen.getByText('Apply failed')).toBeInTheDocument();
			expect(screen.getByRole('button', { name: 'Enable DHCP gateway' })).toBeInTheDocument();
			// It checked the status before reporting the failure
			expect(dhcpApi.getDhcpStatus).toHaveBeenCalledTimes(2);
		});
	});

	describe('enabled', () => {
		it('shows status, issues, notes and the lease table', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(
				status({ leases: LEASES, issues: ['Gateway address missing, re-added'] }),
			);

			render(DhcpGoLive);
			await flush();

			expect(dhcpApi.getDhcpPreflight).not.toHaveBeenCalled();
			expect(screen.getByText('Gateway address missing, re-added')).toBeInTheDocument();
			expect(screen.getByText('Restart NetTap once.')).toBeInTheDocument();
			expect(screen.getByText(/OpenSearch security bootstrap/)).toBeInTheDocument();
			expect(screen.getByText('Double NAT.')).toBeInTheDocument();
			expect(screen.getByText("Turn your router's DHCP server back on.")).toBeInTheDocument();
			// default sort: IP ascending, numeric
			expect(rowCells(1)).toEqual(['10.77.0.9', '10.77.0.23', '10.77.0.100']);
		});

		it('sorts the lease table by every column', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(status({ leases: LEASES }));
			render(DhcpGoLive);
			await flush();

			await fireEvent.click(screen.getByRole('columnheader', { name: /Device/ }));
			expect(rowCells(0)).toEqual(['tv', 'pixel-8', 'laptop']);
			await fireEvent.click(screen.getByRole('columnheader', { name: /Device/ }));
			expect(rowCells(0)).toEqual(['laptop', 'pixel-8', 'tv']);

			await fireEvent.click(screen.getByRole('columnheader', { name: /MAC address/ }));
			expect(rowCells(2)).toEqual(['aa:aa:aa:aa:aa:03', 'aa:aa:aa:aa:aa:02', 'aa:aa:aa:aa:aa:01']);

			await fireEvent.click(screen.getByRole('columnheader', { name: /Lease expires/ }));
			expect(rowCells(0)).toEqual(['tv', 'laptop', 'pixel-8']);

			await fireEvent.click(screen.getByRole('columnheader', { name: /IP address/ }));
			expect(rowCells(1)).toEqual(['10.77.0.100', '10.77.0.23', '10.77.0.9']);
		});

		it('warns about IPv6 when the preflight saw router advertisements', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(NOT_ENABLED);
			vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValue(preflight({ ipv6_router_advertisements: true }));
			vi.mocked(dhcpApi.enableDhcpGateway).mockResolvedValue(status());

			render(DhcpGoLive);
			await flush();
			await fireEvent.click(screen.getByRole('checkbox'));
			await fireEvent.click(screen.getByRole('button', { name: 'Enable DHCP gateway' }));
			await flush();

			expect(screen.getByText('Some traffic skips NetTap.')).toBeInTheDocument();
		});

		it('has no IPv6 warning without router advertisements', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(NOT_ENABLED);
			vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValue(preflight());
			vi.mocked(dhcpApi.enableDhcpGateway).mockResolvedValue(status());

			render(DhcpGoLive);
			await flush();
			await fireEvent.click(screen.getByRole('checkbox'));
			await fireEvent.click(screen.getByRole('button', { name: 'Enable DHCP gateway' }));
			await flush();

			expect(screen.queryByText('Some traffic skips NetTap.')).not.toBeInTheDocument();
		});

		it('polls status every 5 s and stops on destroy', async () => {
			vi.useFakeTimers();
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(status());

			const { unmount } = render(DhcpGoLive);
			await vi.advanceTimersByTimeAsync(0);
			expect(dhcpApi.getDhcpStatus).toHaveBeenCalledTimes(1);

			await vi.advanceTimersByTimeAsync(5000);
			expect(dhcpApi.getDhcpStatus).toHaveBeenCalledTimes(2);
			await vi.advanceTimersByTimeAsync(5000);
			expect(dhcpApi.getDhcpStatus).toHaveBeenCalledTimes(3);

			unmount();
			await vi.advanceTimersByTimeAsync(20_000);
			expect(dhcpApi.getDhcpStatus).toHaveBeenCalledTimes(3);
		});

		it('does not poll before DHCP is enabled', async () => {
			vi.useFakeTimers();
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(NOT_ENABLED);
			vi.mocked(dhcpApi.getDhcpPreflight).mockResolvedValue(preflight());

			render(DhcpGoLive);
			await vi.advanceTimersByTimeAsync(20_000);

			expect(dhcpApi.getDhcpStatus).toHaveBeenCalledTimes(1);
		});

		it('turns off the DHCP server only after confirming, then shows recovery steps', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(status());
			vi.mocked(dhcpApi.disableDhcpGateway).mockResolvedValue(status({ dhcp_enabled: false, dhcp_server_running: false }));

			render(DhcpGoLive);
			await flush();

			await fireEvent.click(screen.getByRole('button', { name: 'Turn off DHCP server' }));
			expect(dhcpApi.disableDhcpGateway).not.toHaveBeenCalled();
			expect(screen.getByText("Turn your router's DHCP server back on first.")).toBeInTheDocument();

			await fireEvent.click(screen.getByRole('button', { name: 'Yes, turn off DHCP server' }));
			await flush();

			expect(dhcpApi.disableDhcpGateway).toHaveBeenCalledTimes(1);
			expect(screen.getByText("NetTap's DHCP server is off.")).toBeInTheDocument();
			expect(screen.getByText("Turn your router's DHCP server back on.")).toBeInTheDocument();
		});

		it('recovery step 1 gives a fixed laptop address from the router network', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(status());

			render(DhcpGoLive);
			await flush();

			const steps = screen.getByText("Turn your router's DHCP server back on.").closest('li');
			const text = (steps?.textContent ?? '').replace(/\s+/g, ' ');
			expect(text).toContain('IP 192.168.1.20, mask 255.255.255.0, then open http://192.168.1.1');
			expect(text).toMatch(/phone app/);
		});

		it('recovery step 1 still explains a fixed address when the router network is unknown', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(status({ upstream: null }));

			render(DhcpGoLive);
			await flush();

			const steps = screen.getByText("Turn your router's DHCP server back on.").closest('li');
			expect(steps?.textContent).toMatch(/free address in the router's range/);
			expect(steps?.textContent).not.toMatch(/http:\/\//);
		});

		it('keeps the enabled view and shows the error when turning off fails', async () => {
			vi.mocked(dhcpApi.getDhcpStatus).mockResolvedValue(status());
			vi.mocked(dhcpApi.disableDhcpGateway).mockRejectedValue(new Error('HTTP 500'));

			render(DhcpGoLive);
			await flush();
			await fireEvent.click(screen.getByRole('button', { name: 'Turn off DHCP server' }));
			await fireEvent.click(screen.getByRole('button', { name: 'Yes, turn off DHCP server' }));
			await flush();

			expect(screen.getByText('HTTP 500')).toBeInTheDocument();
			expect(screen.getByText("NetTap is now your network's gateway.")).toBeInTheDocument();
		});
	});
});
