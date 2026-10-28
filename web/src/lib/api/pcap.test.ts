import { describe, it, expect, vi, afterEach } from 'vitest';
import {
	getPcapFiles,
	searchPcaps,
	previewPcap,
	getDownloadUrl,
	getFileDownloadUrl,
	formatBytes,
} from './pcap';

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

function mockFetchSuccess(body: unknown, status = 200): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: status >= 200 && status < 300,
			status,
			json: () => Promise.resolve(body),
		}),
	);
}

function mockFetchFailure(status = 500, body: unknown = { error: 'fail' }): void {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({
			ok: false,
			status,
			json: () => Promise.resolve(body),
		}),
	);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('pcap API client', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- getPcapFiles -----------------------------------------------------

	describe('getPcapFiles', () => {
		it('returns parsed files on success', async () => {
			const expected = {
				count: 2,
				files: [
					{
						file: '/data/pcap/capture_001.pcap',
						name: 'capture_001.pcap',
						size_bytes: 104,
						modified: '2026-03-08T00:00:00Z',
						relative_path: 'capture_001.pcap',
					},
					{
						file: '/data/pcap/capture_002.pcapng',
						name: 'capture_002.pcapng',
						size_bytes: 204,
						modified: '2026-03-07T00:00:00Z',
						relative_path: 'capture_002.pcapng',
					},
				],
			};
			mockFetchSuccess(expected);

			const result = await getPcapFiles();
			expect(result.count).toBe(2);
			expect(result.files[0].name).toBe('capture_001.pcap');
		});

		it('returns empty on failure', async () => {
			mockFetchFailure();
			const result = await getPcapFiles();
			expect(result.count).toBe(0);
			expect(result.files).toEqual([]);
		});

		it('passes time range params', async () => {
			mockFetchSuccess({ count: 0, files: [] });
			await getPcapFiles({ from: '2026-03-01', to: '2026-03-08' });
			const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('from=2026-03-01');
			expect(url).toContain('to=2026-03-08');
		});
	});

	// -- searchPcaps ------------------------------------------------------

	describe('searchPcaps', () => {
		it('returns search results on success', async () => {
			mockFetchSuccess({
				filter: 'tcp port 80',
				count: 1,
				results: [
					{
						file: '/data/pcap/capture.pcap',
						name: 'capture.pcap',
						size_bytes: 100,
						modified: '2026-03-08T00:00:00Z',
						relative_path: 'capture.pcap',
						matching_packets: 42,
					},
				],
			});

			const result = await searchPcaps('tcp port 80');
			expect(result.count).toBe(1);
			expect(result.results[0].matching_packets).toBe(42);
		});

		it('throws on failure with error message', async () => {
			mockFetchFailure(400, { error: 'Invalid BPF filter' });
			await expect(searchPcaps('bad;filter')).rejects.toThrow('Invalid BPF filter');
		});

		it('includes filter in query', async () => {
			mockFetchSuccess({ filter: 'tcp', count: 0, results: [] });
			await searchPcaps('tcp port 80');
			const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('filter=tcp+port+80');
		});
	});

	// -- previewPcap ------------------------------------------------------

	describe('previewPcap', () => {
		it('returns packets on success', async () => {
			mockFetchSuccess({
				file: '/data/pcap/test.pcap',
				filter: null,
				count: 1,
				packets: [
					{
						frame_number: '1',
						timestamp: '2026-03-08',
						source: '192.168.1.1',
						destination: '8.8.8.8',
						protocol: 'DNS',
						length: '74',
						info: 'Query',
					},
				],
			});

			const result = await previewPcap('/data/pcap/test.pcap');
			expect(result.packets).toHaveLength(1);
			expect(result.packets[0].source).toBe('192.168.1.1');
		});

		it('throws on failure', async () => {
			mockFetchFailure(404, { error: 'File not found' });
			await expect(previewPcap('/missing.pcap')).rejects.toThrow('File not found');
		});

		it('passes filter and limit', async () => {
			mockFetchSuccess({ file: '', filter: '', count: 0, packets: [] });
			await previewPcap('/data/pcap/test.pcap', { filter: 'tcp', limit: 50 });
			const url = (fetch as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
			expect(url).toContain('filter=tcp');
			expect(url).toContain('limit=50');
		});
	});

	// -- getDownloadUrl ---------------------------------------------------

	describe('getDownloadUrl', () => {
		it('builds correct URL', () => {
			const url = getDownloadUrl('tcp port 80', {
				from: '2026-03-01',
				to: '2026-03-08',
			});
			expect(url).toContain('/api/pcap/download');
			expect(url).toContain('filter=tcp+port+80');
			expect(url).toContain('from=2026-03-01');
		});
	});

	// -- getFileDownloadUrl -----------------------------------------------

	describe('getFileDownloadUrl', () => {
		it('builds correct URL for single file download', () => {
			const url = getFileDownloadUrl('/data/pcap/capture_001.pcap');
			expect(url).toBe('/api/pcap/download-file?file=%2Fdata%2Fpcap%2Fcapture_001.pcap');
		});
	});

	// -- formatBytes ------------------------------------------------------

	describe('formatBytes', () => {
		it('formats 0 bytes', () => {
			expect(formatBytes(0)).toBe('0 B');
		});

		it('formats bytes', () => {
			expect(formatBytes(500)).toBe('500.0 B');
		});

		it('formats kilobytes', () => {
			expect(formatBytes(1024)).toBe('1.0 KB');
		});

		it('formats megabytes', () => {
			expect(formatBytes(1048576)).toBe('1.0 MB');
		});

		it('formats gigabytes', () => {
			expect(formatBytes(1073741824)).toBe('1.0 GB');
		});
	});
});
