import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import PanelManager from './PanelManager.svelte';

const samplePackets = [
	{
		'frame.number': '1',
		'ip.src': '192.168.1.10',
		'ip.dst': '8.8.8.8',
		protocol: 'DNS',
		'frame.len': '74',
		info: 'Standard query A google.com',
	},
];

describe('PanelManager', () => {
	it('renders all three panel title bars', () => {
		render(PanelManager, {
			props: {
				packets: samplePackets,
				loading: false,
				selectedPacket: null,
				selectedPacketIndex: -1,
				onPacketSelect: vi.fn(),
			},
		});

		expect(screen.getByText('Packet Table')).toBeInTheDocument();
		expect(screen.getByText('Protocol Tree')).toBeInTheDocument();
		expect(screen.getByText('Hex Dump')).toBeInTheDocument();
	});

	it('renders PacketTable with packets data', () => {
		render(PanelManager, {
			props: {
				packets: samplePackets,
				loading: false,
				selectedPacket: null,
				selectedPacketIndex: -1,
				onPacketSelect: vi.fn(),
			},
		});

		expect(screen.getByText('192.168.1.10')).toBeInTheDocument();
	});

	it('shows protocol tree empty state when no packet selected', () => {
		render(PanelManager, {
			props: {
				packets: samplePackets,
				loading: false,
				selectedPacket: null,
				selectedPacketIndex: -1,
				onPacketSelect: vi.fn(),
			},
		});

		expect(screen.getByText(/select a packet to view protocol/i)).toBeInTheDocument();
	});
});
