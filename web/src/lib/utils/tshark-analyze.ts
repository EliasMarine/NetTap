// ---------------------------------------------------------------------------
// Shared multi-PCAP TShark analysis utility
//
// Sorts PCAPs by timestamp proximity and tries multiple files until packets
// are found. Supports summary, verbose, and follow stream modes.
// ---------------------------------------------------------------------------

import { analyzePcap } from '$api/tshark';
import type { TSharkPacket, TSharkAnalyzeRequest, PcapFile } from '$api/tshark';

export type AnalysisMode = 'summary' | 'verbose' | 'follow';

export interface AnalyzeConnectionOpts {
	pcapFiles: PcapFile[];
	displayFilter: string;
	timestamp: string;
	mode: AnalysisMode;
	proto: string; // 'tcp', 'udp', etc. — used for follow stream protocol
	maxAttempts?: number;
}

export interface AnalyzeConnectionResult {
	packets: TSharkPacket[];
	textOutput: string;
	error: string;
}

/**
 * Sort PCAPs by proximity to a connection timestamp.
 * Closest modified time to the connection comes first.
 */
export function sortPcapsByTimestamp(pcaps: PcapFile[], timestamp: string): PcapFile[] {
	const connTs = timestamp ? new Date(timestamp).getTime() : Date.now();
	return [...pcaps].sort(
		(a, b) => Math.abs(a.modified * 1000 - connTs) - Math.abs(b.modified * 1000 - connTs),
	);
}

/**
 * Build the API request params based on analysis mode.
 */
export function buildRequestForMode(
	pcapPath: string,
	displayFilter: string,
	mode: AnalysisMode,
	proto: string,
): TSharkAnalyzeRequest {
	const base: TSharkAnalyzeRequest = {
		pcap_path: pcapPath,
		display_filter: displayFilter,
	};

	switch (mode) {
		case 'summary':
			return { ...base, output_format: 'json', max_packets: 100 };
		case 'verbose':
			return { ...base, output_format: 'text', verbose: true, max_packets: 20 };
		case 'follow': {
			const followProto = (proto || 'tcp').toLowerCase();
			return { ...base, output_format: 'text', follow_stream: followProto as TSharkAnalyzeRequest['follow_stream'], max_packets: 500 };
		}
	}
}

/**
 * Analyze a connection across multiple PCAPs, trying each in order of
 * timestamp proximity until packets are found.
 */
export async function analyzeConnection(opts: AnalyzeConnectionOpts): Promise<AnalyzeConnectionResult> {
	const { pcapFiles, displayFilter, timestamp, mode, proto, maxAttempts = 5 } = opts;

	if (pcapFiles.length === 0) {
		return { packets: [], textOutput: '', error: 'No PCAP files available on the appliance.' };
	}
	if (!displayFilter) {
		return { packets: [], textOutput: '', error: 'Could not build a display filter from this connection.' };
	}

	const sorted = sortPcapsByTimestamp(pcapFiles, timestamp);
	const attempts = sorted.slice(0, maxAttempts);

	for (const pcap of attempts) {
		try {
			const req = buildRequestForMode(pcap.path, displayFilter, mode, proto);
			const result = await analyzePcap(req);

			if (result.error) continue;
			if (!result.packets || result.packets.length === 0) continue;

			if (mode === 'summary') {
				return { packets: result.packets, textOutput: '', error: '' };
			}

			// verbose / follow: extract raw text from packets array
			const text = result.packets
				.map((p) => {
					if (typeof p === 'string') return p;
					return p?.raw || p?.text || JSON.stringify(p, null, 2);
				})
				.join('\n');

			return { packets: result.packets, textOutput: text, error: '' };
		} catch {
			continue;
		}
	}

	return {
		packets: [],
		textOutput: '',
		error: `No matching packets found after searching ${attempts.length} PCAP file${attempts.length !== 1 ? 's' : ''}.`,
	};
}
