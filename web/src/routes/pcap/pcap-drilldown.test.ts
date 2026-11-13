import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import Page from './+page.svelte';
import * as api from '$lib/api/pcap';
import type { PcapFile } from '$lib/api/pcap';

// NET-249 slice 2: the capture timeline's slots are epoch-aligned on the owner's buckets, and a pick
// narrows the file list to the files whose `modified` falls in the picked slots: the chart's own rule

vi.mock('$lib/api/pcap', async (importActual) => ({
	...(await importActual<typeof import('$lib/api/pcap')>()),
	getPcapFiles: vi.fn(),
	searchPcaps: vi.fn(),
	previewPcap: vi.fn(),
}));
vi.mock('$lib/api/capture', async (importActual) => ({
	...(await importActual<typeof import('$lib/api/capture')>()),
	fetchCaptureStatus: vi.fn(async () => ({ enabled: true, maxFileSizeMB: 256, rotateMinutes: 10, containerRunning: true, containerStatus: 'running' })),
}));

const file = (name: string, modified: string): PcapFile => ({ file: `/pcap/${name}`, name, size_bytes: 1000, modified, relative_path: name });
// The page's 1h window is 09:00:30 to 10:00:30, so its 1-minute slots run from 09:00 to 10:00
const FILES = [
	file('a.pcap', '2026-11-13T09:30:10.000Z'),
	file('b.pcap', '2026-11-13T09:30:59.999Z'),
	file('c.pcap', '2026-11-13T09:31:00.000Z'),
	// written just before the slot: its capture may overlap it, but the chart counts it a minute earlier
	file('d.pcap', '2026-11-13T09:29:59.000Z'),
	// listed for the window (its capture overlaps it), written after it: on no slot
	file('e.pcap', '2026-11-13T10:05:00.000Z'),
];

async function flush() {
	for (let i = 0; i < 5; i++) await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));
}

const listed = () => {
	const table = screen.getByRole('table', { name: 'PCAP files' });
	return FILES.map((f) => f.name).filter((name) => within(table).queryByText(name));
};

describe('PCAP — the capture timeline narrows the file list (NET-249)', () => {
	beforeEach(() => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-11-13T10:00:30Z'));
		vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
		vi.mocked(api.getPcapFiles).mockResolvedValue({ count: FILES.length, files: FILES });
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		vi.clearAllMocks();
	});

	async function chartAt(slot: number) {
		render(Page);
		await flush();
		const chart = screen.getByRole('group', { name: /^Most files at / });
		await fireEvent.keyDown(chart, { key: 'Home' });
		for (let i = 0; i < slot; i++) await fireEvent.keyDown(chart, { key: 'ArrowRight' });
		return chart;
	}

	it('draws epoch-aligned 1-minute slots over the listed window, counting files by when they were written', async () => {
		render(Page);
		await flush();
		expect(screen.getByText(/^Files written per minute · last hour/)).toBeInTheDocument();
		// a.pcap and b.pcap share the 09:30 slot
		expect(screen.getByRole('group', { name: /^Most files at .*, with 2 written/ })).toBeInTheDocument();
		expect(screen.getByText('Click a point or drag across the chart to list the files written then.')).toBeInTheDocument();
		expect(listed()).toEqual(FILES.map((f) => f.name));
	});

	it('a pick lists only the files written in that slot, and Show all lists them all again', async () => {
		const chart = await chartAt(30); // 09:30
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(listed()).toEqual(['a.pcap', 'b.pcap']);
		expect(screen.getByText(/^Showing the 2 files written .*, of the 5 files listed\.$/)).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Show all' }));
		expect(listed()).toEqual(FILES.map((f) => f.name));
	});

	it('a keyboard range lists the files written across it', async () => {
		const chart = await chartAt(30);
		await fireEvent.keyDown(chart, { key: 'ArrowRight', shiftKey: true });
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(listed()).toEqual(['a.pcap', 'b.pcap', 'c.pcap']);
	});

	it('an empty slot says no file was written then', async () => {
		const chart = await chartAt(5);
		await fireEvent.keyDown(chart, { key: 'Enter' });
		expect(screen.getByText('No file was written then.')).toBeInTheDocument();
		expect(screen.getByText(/^Showing the 0 files written /)).toBeInTheDocument();
	});

	it('another range clears the pick', async () => {
		const chart = await chartAt(30);
		await fireEvent.keyDown(chart, { key: 'Enter' });
		await fireEvent.click(screen.getByRole('button', { name: '6h' }));
		await flush();
		expect(screen.queryByText(/^Showing the /)).not.toBeInTheDocument();
		expect(listed()).toEqual(FILES.map((f) => f.name));
	});
});
