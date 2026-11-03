import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import PacketTable from './PacketTable.svelte';

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const samplePackets = [
	{
		'frame.number': '1',
		'frame.time_relative': '0.000000',
		'ip.src': '192.168.1.10',
		'ip.dst': '8.8.8.8',
		protocol: 'DNS',
		'frame.len': '74',
		info: 'Standard query A google.com',
	},
	{
		'frame.number': '2',
		'frame.time_relative': '0.012345',
		'ip.src': '10.0.0.5',
		'ip.dst': '142.250.80.46',
		protocol: 'DNS',
		'frame.len': '90',
		info: 'Standard query response A 142.250.80.46',
	},
	{
		'frame.number': '3',
		'frame.time_relative': '0.050000',
		'ip.src': '172.16.0.1',
		'ip.dst': '93.184.216.34',
		protocol: 'TCP',
		'frame.len': '66',
		info: 'SYN [TCP Flags]',
	},
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('PacketTable component', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it('shows "No packets" message when packets array is empty', () => {
		const onselect = vi.fn();
		render(PacketTable, { props: { packets: [], onselect } });

		expect(screen.getByText(/no packets to display/i)).toBeInTheDocument();
	});

	it('renders table headers', () => {
		const onselect = vi.fn();
		const { container } = render(PacketTable, { props: { packets: [], onselect } });

		const thead = container.querySelector('thead')!;
		expect(thead).not.toBeNull();

		const ths = thead.querySelectorAll('th');
		const headerTexts = Array.from(ths).map((th) => th.textContent?.trim());

		expect(headerTexts).toEqual(['No.↑', 'Time', 'Source', 'Destination', 'Protocol', 'Length', 'Info']);
	});

	it('renders rows for each packet', () => {
		const onselect = vi.fn();
		const { container } = render(PacketTable, { props: { packets: samplePackets, onselect } });

		// Each packet creates a row with tabindex="0"
		const dataRows = container.querySelectorAll('tr[tabindex="0"]');
		expect(dataRows.length).toBe(3);

		// Check that unique source IPs appear
		expect(screen.getByText('192.168.1.10')).toBeInTheDocument();
		expect(screen.getByText('10.0.0.5')).toBeInTheDocument();
		expect(screen.getByText('172.16.0.1')).toBeInTheDocument();

		// Check that unique packet info appears
		expect(screen.getByText('Standard query A google.com')).toBeInTheDocument();
		expect(screen.getByText('SYN [TCP Flags]')).toBeInTheDocument();
	});

	it('shows loading overlay when loading is true', () => {
		const onselect = vi.fn();
		render(PacketTable, { props: { packets: [], loading: true, onselect } });

		expect(screen.getByText(/analyzing packets/i)).toBeInTheDocument();
	});

	it('does not show loading overlay when loading is false', () => {
		const onselect = vi.fn();
		const { container } = render(PacketTable, { props: { packets: samplePackets, loading: false, onselect } });

		// The loading overlay has the class "table-overlay"
		const overlay = container.querySelector('.table-overlay');
		expect(overlay).toBeNull();
	});

	it('calls onselect when a row is clicked', async () => {
		const onselect = vi.fn();
		const { container } = render(PacketTable, { props: { packets: samplePackets, onselect } });

		// Click the first data row
		const firstRow = container.querySelector('tr[tabindex="0"]')!;
		expect(firstRow).not.toBeNull();
		await fireEvent.click(firstRow);

		expect(onselect).toHaveBeenCalledOnce();
		expect(onselect).toHaveBeenCalledWith(samplePackets[0]);
	});

	it('marks the selected row with aria-selected', () => {
		const onselect = vi.fn();
		const { container } = render(PacketTable, {
			props: { packets: samplePackets, onselect, selectedIndex: 1 },
		});

		const dataRows = container.querySelectorAll('tr[tabindex="0"]');
		expect(dataRows.length).toBe(3);

		expect(dataRows[0].getAttribute('aria-selected')).toBe('false');
		expect(dataRows[1].getAttribute('aria-selected')).toBe('true');
		expect(dataRows[2].getAttribute('aria-selected')).toBe('false');
	});

	it('sorts by a clicked column and keeps the selection on the same packet', async () => {
		const onselect = vi.fn();
		const { container } = render(PacketTable, {
			props: { packets: samplePackets, onselect, selectedIndex: 1 },
		});
		const header = (label: string) =>
			Array.from(container.querySelectorAll('th')).find((th) => th.textContent?.startsWith(label))!;
		const firstCells = () =>
			Array.from(container.querySelectorAll('tr[tabindex="0"]')).map((r) => r.querySelector('td')!.textContent);

		expect(firstCells()).toEqual(['1', '2', '3']);

		await fireEvent.click(header('Length')); // first click: largest first
		expect(firstCells()).toEqual(['2', '1', '3']);
		const rows = container.querySelectorAll('tr[tabindex="0"]');
		// packet 2 (selectedIndex 1 in capture order) is now the top row
		expect(rows[0].getAttribute('aria-selected')).toBe('true');
		expect(rows[1].getAttribute('aria-selected')).toBe('false');

		await fireEvent.click(header('Length'));
		expect(firstCells()).toEqual(['3', '1', '2']);
	});

	// #141: frame.protocols ends in "data" when tshark can't decode the payload
	it("shows Wireshark's Protocol column, not the last frame.protocols entry", () => {
		const onselect = vi.fn();
		const pkt = {
			_source: {
				layers: {
					frame: { 'frame.number': '1', 'frame.protocols': 'eth:ethertype:ip:udp:data', 'frame.len': '1494' },
					ip: { 'ip.src': '52.84.234.39', 'ip.dst': '192.168.1.151' },
					'_ws.col.Protocol': 'UDP',
					'_ws.col.Info': '443 → 56647 Len=1452',
				},
			},
		};
		const { container } = render(PacketTable, { props: { packets: [pkt], onselect } });
		expect(container.querySelector('tbody .col-proto')!.textContent?.trim()).toBe('UDP');
	});

	it('does not show empty-state message when packets exist', () => {
		const onselect = vi.fn();
		render(PacketTable, { props: { packets: samplePackets, onselect } });

		expect(screen.queryByText(/no packets to display/i)).not.toBeInTheDocument();
	});
});
