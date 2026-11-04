import type { PcapFile, PcapFilesResponse } from '../../../src/lib/api/pcap.ts';
import { HOUR, iso, type FixtureRoute } from './types.ts';
import { MB } from './net-world.ts';

// Malcolm's 256 MB rotation: five files, the newest still filling.
const files: PcapFile[] = [48, 36, 22, 9, 1].map((hoursAgo, i) => {
	const name = `nettap-mirror_${String(i + 1).padStart(5, '0')}.pcap`;
	return {
		file: `/pcap/processed/${name}`,
		name,
		size_bytes: i === 4 ? 91 * MB : 256 * MB,
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
