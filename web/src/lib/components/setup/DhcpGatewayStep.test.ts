import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import DhcpGatewayStep from './DhcpGatewayStep.svelte';

// The bind:valid wiring is covered by the wizard test (an invalid subnet disables Next).

describe('DhcpGatewayStep', () => {
	it('starts with the default subnet and no error', () => {
		render(DhcpGatewayStep, { props: { nicAddresses: ['192.168.1.50'], selectedInterface: 'enp1s0' } });

		const input = screen.getByLabelText(/Subnet for your devices/) as HTMLInputElement;
		expect(input.value).toBe('10.77.0.0/24');
		expect(input).toHaveAttribute('aria-invalid', 'false');
		expect(screen.getByText(/Looks good/)).toBeInTheDocument();
	});

	it('shows a plain-English error as the user types an invalid subnet', async () => {
		render(DhcpGatewayStep, { props: { nicAddresses: [], selectedInterface: 'enp1s0' } });
		const input = screen.getByLabelText(/Subnet for your devices/);

		await fireEvent.input(input, { target: { value: '10.77.0.5/24' } });

		expect(input).toHaveAttribute('aria-invalid', 'true');
		expect(screen.getByText(/Did you mean 10.77.0.0\/24\?/)).toBeInTheDocument();
	});

	it("rejects a subnet that contains one of NetTap's own addresses", async () => {
		render(DhcpGatewayStep, { props: { nicAddresses: ['192.168.1.50'], selectedInterface: 'enp1s0' } });

		await fireEvent.input(screen.getByLabelText(/Subnet for your devices/), { target: { value: '192.168.1.0/24' } });

		expect(screen.getByText(/includes 192.168.1.50/)).toBeInTheDocument();
	});

	it('explains what happens next, naming the chosen port', () => {
		render(DhcpGatewayStep, { props: { nicAddresses: [], selectedInterface: 'enp1s0' } });

		expect(screen.getByText(/turn off your router's DHCP server/)).toBeInTheDocument();
		expect(screen.getByText('enp1s0')).toBeInTheDocument();
		expect(screen.getByText(/routes your devices' traffic on to your router/)).toBeInTheDocument();
	});

	it('lists the four limitations', () => {
		render(DhcpGatewayStep, { props: { nicAddresses: [], selectedInterface: 'enp1s0' } });

		expect(screen.getByText(/double NAT/)).toBeInTheDocument();
		expect(screen.getByText(/IPv6/)).toBeInTheDocument();
		expect(screen.getByText(/manually set IP address/)).toBeInTheDocument();
		expect(screen.getByText(/must stay powered on/)).toBeInTheDocument();
	});
});
