import type { PcapFile, PcapFilesResponse } from '../../../src/lib/api/pcap.ts';
import { HOUR, iso, type FixtureRoute } from './types.ts';
// OLD CODE: import { MB } from './net-world.ts'; (NET-166: net-world's MB is decimal; netsniff-ng rotates in MiB)
const MIB = 1024 ** 2;

// The 256 MiB rotation (netsniff-ng's PCAP_ROTATE_MB counts MiB, so a full file reads 268.4 MB):
// five files, the newest still filling.
const files: PcapFile[] = [48, 36, 22, 9, 1].map((hoursAgo, i) => {
	const name = `nettap-mirror_${String(i + 1).padStart(5, '0')}.pcap`;
	return {
		file: `/pcap/processed/${name}`,
		name,
		size_bytes: i === 4 ? 91 * MIB : 256 * MIB,
		modified: iso(hoursAgo * HOUR),
		relative_path: `processed/${name}`,
	};
}).reverse();

export const PCAP_ROUTES: FixtureRoute[] = [
	{
		path: '/api/pcap/files',
		empty: { count: 0, files: [] } satisfies PcapFilesResponse,
		populated: { count: files.length, files } satisfies PcapFilesResponse,
	},
];
