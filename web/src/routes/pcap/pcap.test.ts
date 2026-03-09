import { describe, it, expect, vi, afterEach } from 'vitest';
import { getPcapFiles, searchPcaps, previewPcap, getDownloadUrl, formatBytes } from '$lib/api/pcap';

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
