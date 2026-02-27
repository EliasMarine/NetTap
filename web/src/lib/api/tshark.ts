/**
 * Client-side API helpers for the TShark packet analysis endpoints.
 * These functions call the SvelteKit server proxy routes which in turn
 * forward requests to the nettap-storage-daemon.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TSharkAnalyzeRequest {
	pcap_path: string;
	display_filter?: string;
	max_packets?: number;
	output_format?: 'json' | 'text';
	fields?: string[];
}

export interface TSharkPacket {
	[key: string]: any;
}

export interface TSharkAnalyzeResponse {
	packets: TSharkPacket[];
	packet_count: number;
	truncated: boolean;
	tshark_version: string;
	error?: string;
}

export interface TSharkStatus {
	available: boolean;
	version: string;
	container_running: boolean;
	container_name: string;
}

export interface TSharkProtocol {
	name: string;
	description?: string;
	[key: string]: any;
}

export interface TSharkField {
	name: string;
	description?: string;
	type?: string;
	[key: string]: any;
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

/**
 * Analyze a PCAP file using TShark via the SvelteKit proxy.
 */
export async function analyzePcap(req: TSharkAnalyzeRequest): Promise<TSharkAnalyzeResponse> {
	const res = await fetch('/api/tshark/analyze', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(req),
	});

	if (!res.ok) {
		const body = await res.json().catch(() => ({}));
		return {
			packets: [],
			packet_count: 0,
			truncated: false,
			tshark_version: '',
			error: body.error || `Analysis failed (HTTP ${res.status})`,
		};
	}

	return res.json();
}

/**
 * Get TShark availability and version information.
 */
export async function getTSharkStatus(): Promise<TSharkStatus> {
	const res = await fetch('/api/tshark/status');

	if (!res.ok) {
		return {
			available: false,
			version: '',
			container_running: false,
			container_name: '',
		};
	}

	return res.json();
}

/**
 * Retrieve the list of protocols known to TShark.
 */
export async function getProtocols(): Promise<{ protocols: TSharkProtocol[]; count: number }> {
	const res = await fetch('/api/tshark/protocols');

	if (!res.ok) {
		return { protocols: [], count: 0 };
	}

	return res.json();
}

/**
 * Retrieve the dissector fields for a given protocol.
 * If no protocol is supplied the daemon returns all fields.
 */
export async function getFields(
	protocol?: string
): Promise<{ fields: TSharkField[]; count: number }> {
	const params = protocol ? `?protocol=${encodeURIComponent(protocol)}` : '';
	const res = await fetch(`/api/tshark/fields${params}`);

	if (!res.ok) {
		return { fields: [], count: 0 };
	}

	return res.json();
}
