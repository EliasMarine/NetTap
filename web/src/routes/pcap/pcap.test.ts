import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { getPcapFiles, searchPcaps, previewPcap, getDownloadUrl, formatBytes } from '$lib/api/pcap';
import PcapPage from './+page.svelte';

/**
 * Page-level tests for the PCAP search page.
 * Tests the API integration functions used by the page.
 */

function mockFetchSuccess(body: unknown): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: () => Promise.resolve(body),
		}),
	);
}

describe('PCAP search page integration', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it('loads available PCAP files', async () => {
		mockFetchSuccess({
			count: 1,
			files: [
				{
					file: '/data/pcap/test.pcap',
					name: 'test.pcap',
					size_bytes: 1024,
					modified: '2026-03-08T00:00:00Z',
					relative_path: 'test.pcap',
				},
			],
		});

		const result = await getPcapFiles();
		expect(result.files).toHaveLength(1);
		expect(result.files[0].name).toBe('test.pcap');
	});

	it('searches PCAPs with BPF filter', async () => {
		mockFetchSuccess({
			filter: 'tcp port 80',
			count: 1,
			results: [
				{
					file: '/data/pcap/test.pcap',
					name: 'test.pcap',
					size_bytes: 1024,
					modified: '2026-03-08T00:00:00Z',
					relative_path: 'test.pcap',
					matching_packets: 42,
				},
			],
		});

		const result = await searchPcaps('tcp port 80');
		expect(result.results[0].matching_packets).toBe(42);
	});

	it('previews packets from a PCAP file', async () => {
		mockFetchSuccess({
			file: '/data/pcap/test.pcap',
			filter: null,
			count: 1,
			packets: [
				{
					frame_number: '1',
					timestamp: '2026-03-08T00:00:00',
					source: '192.168.1.1',
					destination: '8.8.8.8',
					protocol: 'DNS',
					length: '74',
					info: 'Standard query A google.com',
				},
			],
		});

		const result = await previewPcap('/data/pcap/test.pcap');
		expect(result.packets).toHaveLength(1);
		expect(result.packets[0].protocol).toBe('DNS');
	});

	it('generates correct download URL', () => {
		const url = getDownloadUrl('tcp port 80', {
			from: '2026-03-01T00:00:00Z',
			to: '2026-03-08T00:00:00Z',
		});
		expect(url).toContain('/api/pcap/download');
		expect(url).toContain('filter=');
	});

	it('formats bytes correctly', () => {
		expect(formatBytes(0)).toBe('0 B');
		expect(formatBytes(1024)).toBe('1.0 KB');
		expect(formatBytes(1048576)).toBe('1.0 MB');
	});
});

// ---------------------------------------------------------------------------
// Rendered page: capture status header
// ---------------------------------------------------------------------------

describe('PCAP page — capture status', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	/** /api/capture/status gets `status` (or a network error when null); everything else 500s. */
	async function renderWithCaptureStatus(status: Record<string, unknown> | null) {
		vi.stubGlobal(
			'fetch',
			vi.fn(async (url: string) => {
				if (url.startsWith('/api/capture/status')) {
					if (!status) throw new Error('network error');
					return { ok: true, status: 200, json: async () => status };
				}
				return { ok: false, status: 500, json: async () => ({}) };
			}),
		);
		render(PcapPage);
		for (let i = 0; i < 5; i++) await Promise.resolve();
		await new Promise((r) => setTimeout(r, 0));
	}

	it('says Active when enabled and the container is running', async () => {
		await renderWithCaptureStatus({ enabled: true, maxFileSizeMB: 100, containerRunning: true, containerStatus: 'running' });

		expect(screen.getByText('Capture Active')).toBeInTheDocument();
	});

	it('does not say Active when enabled but the container is down', async () => {
		await renderWithCaptureStatus({ enabled: true, maxFileSizeMB: 100, containerRunning: false, containerStatus: 'exited' });

		expect(screen.getByText('Capture Stopped')).toBeInTheDocument();
		expect(screen.queryByText('Capture Active')).not.toBeInTheDocument();
	});

	it('says the status is unknown when it cannot be read', async () => {
		await renderWithCaptureStatus(null);

		expect(screen.getByText('Capture Status Unknown')).toBeInTheDocument();
		expect(screen.queryByText('Capture Active')).not.toBeInTheDocument();
	});
});
