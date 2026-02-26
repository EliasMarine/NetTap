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

		expect(headerTexts).toEqual(['No.', 'Time', 'Source', 'Destination', 'Protocol', 'Length', 'Info']);
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

	it('does not show empty-state message when packets exist', () => {
		const onselect = vi.fn();
		render(PacketTable, { props: { packets: samplePackets, onselect } });

		expect(screen.queryByText(/no packets to display/i)).not.toBeInTheDocument();
	});
});
