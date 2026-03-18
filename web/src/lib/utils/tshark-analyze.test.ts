import { describe, it, expect, vi, beforeEach } from 'vitest';
import { sortPcapsByTimestamp, buildRequestForMode, analyzeConnection } from './tshark-analyze';
import type { PcapFile } from '$api/tshark';

// ---------------------------------------------------------------------------
// sortPcapsByTimestamp
// ---------------------------------------------------------------------------

describe('sortPcapsByTimestamp', () => {
	const pcaps: PcapFile[] = [
		{ path: '/pcap/old.pcap', relative_path: 'old.pcap', name: 'old.pcap', size_bytes: 1000, modified: 1000 },
		{ path: '/pcap/close.pcap', relative_path: 'close.pcap', name: 'close.pcap', size_bytes: 2000, modified: 1710000 },
		{ path: '/pcap/newest.pcap', relative_path: 'newest.pcap', name: 'newest.pcap', size_bytes: 3000, modified: 2000000 },
	];

	it('sorts by proximity to connection timestamp', () => {
		// Connection at modified=1710000 * 1000 = 1710000000 ms => closest is 'close.pcap'
		const sorted = sortPcapsByTimestamp(pcaps, new Date(1710000 * 1000).toISOString());
		expect(sorted[0].name).toBe('close.pcap');
	});

	it('sorts newest first when no timestamp provided', () => {
		// With empty timestamp, uses Date.now() — newest pcap is closest
		const sorted = sortPcapsByTimestamp(pcaps, '');
		expect(sorted[0].name).toBe('newest.pcap');
	});

	it('does not mutate the original array', () => {
		const original = [...pcaps];
		sortPcapsByTimestamp(pcaps, new Date(1710000 * 1000).toISOString());
		expect(pcaps).toEqual(original);
	});
});

// ---------------------------------------------------------------------------
// buildRequestForMode
// ---------------------------------------------------------------------------

describe('buildRequestForMode', () => {
	it('builds summary request with json format', () => {
		const req = buildRequestForMode('/pcap/test.pcap', 'ip.addr == 10.0.0.1', 'summary', 'tcp');
		expect(req.output_format).toBe('json');
		expect(req.max_packets).toBe(100);
		expect(req.verbose).toBeUndefined();
		expect(req.follow_stream).toBeUndefined();
	});

	it('builds verbose request with -V flag', () => {
		const req = buildRequestForMode('/pcap/test.pcap', 'ip.addr == 10.0.0.1', 'verbose', 'tcp');
		expect(req.output_format).toBe('text');
		expect(req.verbose).toBe(true);
		expect(req.max_packets).toBe(20);
	});

	it('builds follow request with follow_stream proto', () => {
		const req = buildRequestForMode('/pcap/test.pcap', 'ip.addr == 10.0.0.1', 'follow', 'tcp');
		expect(req.follow_stream).toBe('tcp');
		expect(req.output_format).toBe('text');
	});

	it('defaults follow protocol to tcp when empty', () => {
		const req = buildRequestForMode('/pcap/test.pcap', 'filter', 'follow', '');
		expect(req.follow_stream).toBe('tcp');
	});
});

// ---------------------------------------------------------------------------
// analyzeConnection
// ---------------------------------------------------------------------------

// Mock the analyzePcap import
vi.mock('$api/tshark', () => ({
	analyzePcap: vi.fn(),
}));

import { analyzePcap } from '$api/tshark';

const mockAnalyze = vi.mocked(analyzePcap);

describe('analyzeConnection', () => {
	const pcaps: PcapFile[] = [
		{ path: '/pcap/a.pcap', relative_path: 'a.pcap', name: 'a.pcap', size_bytes: 1000, modified: 100 },
		{ path: '/pcap/b.pcap', relative_path: 'b.pcap', name: 'b.pcap', size_bytes: 2000, modified: 200 },
		{ path: '/pcap/c.pcap', relative_path: 'c.pcap', name: 'c.pcap', size_bytes: 3000, modified: 300 },
	];

	beforeEach(() => {
		mockAnalyze.mockReset();
	});

	it('returns error when no PCAP files', async () => {
		const result = await analyzeConnection({
			pcapFiles: [],
			displayFilter: 'ip.addr == 10.0.0.1',
			timestamp: '2024-01-01T00:00:00Z',
			mode: 'summary',
			proto: 'tcp',
		});
		expect(result.error).toContain('No PCAP files');
	});

	it('returns error when no display filter', async () => {
		const result = await analyzeConnection({
			pcapFiles: pcaps,
			displayFilter: '',
			timestamp: '2024-01-01T00:00:00Z',
			mode: 'summary',
			proto: 'tcp',
		});
		expect(result.error).toContain('display filter');
	});

	it('tries multiple PCAPs on failure', async () => {
		mockAnalyze
			.mockResolvedValueOnce({ packets: [], packet_count: 0, truncated: false, tshark_version: '' })
			.mockResolvedValueOnce({
				packets: [{ _source: { layers: { frame: {} } } }],
				packet_count: 1,
				truncated: false,
				tshark_version: 'v4',
			});

		const result = await analyzeConnection({
			pcapFiles: pcaps,
			displayFilter: 'ip.addr == 10.0.0.1',
			timestamp: new Date(200 * 1000).toISOString(),
			mode: 'summary',
			proto: 'tcp',
		});

		expect(result.error).toBe('');
		expect(result.packets.length).toBe(1);
		expect(mockAnalyze).toHaveBeenCalledTimes(2);
	});

	it('returns descriptive error when all PCAPs exhausted', async () => {
		mockAnalyze.mockResolvedValue({ packets: [], packet_count: 0, truncated: false, tshark_version: '' });

		const result = await analyzeConnection({
			pcapFiles: pcaps,
			displayFilter: 'ip.addr == 10.0.0.1',
			timestamp: '2024-01-01T00:00:00Z',
			mode: 'summary',
			proto: 'tcp',
			maxAttempts: 2,
		});

		expect(result.error).toContain('No matching packets');
		expect(result.error).toContain('2 PCAP files');
		expect(mockAnalyze).toHaveBeenCalledTimes(2);
	});

	it('returns text output for verbose mode', async () => {
		mockAnalyze.mockResolvedValueOnce({
			packets: [{ raw: 'Frame 1: verbose output line 1' }, { raw: 'Frame 1: verbose output line 2' }],
			packet_count: 2,
			truncated: false,
			tshark_version: 'v4',
		});

		const result = await analyzeConnection({
			pcapFiles: pcaps,
			displayFilter: 'ip.addr == 10.0.0.1',
			timestamp: '2024-01-01T00:00:00Z',
			mode: 'verbose',
			proto: 'tcp',
		});

		expect(result.textOutput).toContain('verbose output line 1');
		expect(result.textOutput).toContain('verbose output line 2');
	});

	it('sends correct API params for summary mode', async () => {
		mockAnalyze.mockResolvedValueOnce({
			packets: [{ test: true }],
			packet_count: 1,
			truncated: false,
			tshark_version: 'v4',
		});

		await analyzeConnection({
			pcapFiles: pcaps,
			displayFilter: 'ip.addr == 10.0.0.1',
			timestamp: '2024-01-01T00:00:00Z',
			mode: 'summary',
			proto: 'tcp',
		});

		expect(mockAnalyze).toHaveBeenCalledWith(
			expect.objectContaining({
				output_format: 'json',
				max_packets: 100,
			}),
		);
	});

	it('sends verbose=true for verbose mode', async () => {
		mockAnalyze.mockResolvedValueOnce({
			packets: [{ raw: 'test' }],
			packet_count: 1,
			truncated: false,
			tshark_version: 'v4',
		});

		await analyzeConnection({
			pcapFiles: pcaps,
			displayFilter: 'filter',
			timestamp: '2024-01-01T00:00:00Z',
			mode: 'verbose',
			proto: 'tcp',
		});

		expect(mockAnalyze).toHaveBeenCalledWith(
			expect.objectContaining({
				verbose: true,
				output_format: 'text',
				max_packets: 20,
			}),
		);
	});

	it('sends follow_stream for follow mode', async () => {
		mockAnalyze.mockResolvedValueOnce({
			packets: [{ raw: 'stream content' }],
			packet_count: 1,
			truncated: false,
			tshark_version: 'v4',
		});

		await analyzeConnection({
			pcapFiles: pcaps,
			displayFilter: 'filter',
			timestamp: '2024-01-01T00:00:00Z',
			mode: 'follow',
			proto: 'udp',
		});

		expect(mockAnalyze).toHaveBeenCalledWith(
			expect.objectContaining({
				follow_stream: 'udp',
				output_format: 'text',
			}),
		);
	});

	it('skips PCAPs that return errors', async () => {
		mockAnalyze
			.mockResolvedValueOnce({ packets: [], packet_count: 0, truncated: false, tshark_version: '', error: 'bad pcap' })
			.mockResolvedValueOnce({
				packets: [{ test: true }],
				packet_count: 1,
				truncated: false,
				tshark_version: 'v4',
			});

		const result = await analyzeConnection({
			pcapFiles: pcaps,
			displayFilter: 'filter',
			timestamp: '2024-01-01T00:00:00Z',
			mode: 'summary',
			proto: 'tcp',
		});

		expect(result.error).toBe('');
		expect(result.packets.length).toBe(1);
	});

	it('handles thrown exceptions from analyzePcap', async () => {
		mockAnalyze
			.mockRejectedValueOnce(new Error('network error'))
			.mockResolvedValueOnce({
				packets: [{ test: true }],
				packet_count: 1,
				truncated: false,
				tshark_version: 'v4',
			});

		const result = await analyzeConnection({
			pcapFiles: pcaps,
			displayFilter: 'filter',
			timestamp: '2024-01-01T00:00:00Z',
			mode: 'summary',
			proto: 'tcp',
		});

		expect(result.error).toBe('');
		expect(result.packets.length).toBe(1);
	});
});
