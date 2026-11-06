import type { CyberChefStatus, getRecipes } from '../../../src/lib/api/cyberchef.ts';
import type { TSharkStatus, getPcapFiles } from '../../../src/lib/api/tshark.ts';
import { DAY, HOUR, NOW, type FixtureRoute } from './types.ts';

type RecipesResponse = Awaited<ReturnType<typeof getRecipes>>;
type PcapFilesResponse = Awaited<ReturnType<typeof getPcapFiles>>;

/** Not deployed in `empty` (it is an optional container), so /tools/cyberchef shows its offline state and loads no iframe. */
const CYBERCHEF_EMPTY = {
	available: false,
	version: '',
	container_running: false,
	container_name: 'nettap-cyberchef',
} satisfies CyberChefStatus;

const CYBERCHEF_POPULATED = {
	available: true,
	version: '10.19.4',
	container_running: true,
	container_name: 'nettap-cyberchef',
} satisfies CyberChefStatus;

const RECIPES_POPULATED = {
	recipes: [
		{
			name: 'Base64 Decode',
			description: 'Decode Base64 encoded data (common in HTTP payloads and email)',
			category: 'decode',
			recipe_fragment: "#recipe=From_Base64('A-Za-z0-9%2B/%3D',true,false)",
		},
		{
			name: 'URL Decode',
			description: 'Decode URL-encoded (percent-encoded) strings',
			category: 'decode',
			recipe_fragment: '#recipe=URL_Decode()',
		},
		{
			name: 'Hex Decode',
			description: 'Convert hex-encoded data to raw bytes',
			category: 'decode',
			recipe_fragment: "#recipe=From_Hex('Auto')",
		},
		{
			name: 'Extract URLs',
			description: 'Extract all URLs from text or binary data',
			category: 'forensic',
			recipe_fragment: '#recipe=Extract_URLs(false)',
		},
		{
			name: 'Extract IP Addresses',
			description: 'Extract all IPv4 and IPv6 addresses from data',
			category: 'network',
			recipe_fragment: '#recipe=Extract_IP_addresses(true,true,true)',
		},
		{
			name: 'Defang URL',
			description: 'Defang URLs for safe sharing (hxxps://)',
			category: 'network',
			recipe_fragment: "#recipe=Defang_URL(true,true,true,'Valid domains and full URLs')",
		},
		{
			name: 'Parse TLS Certificate',
			description: 'Parse and display X.509 certificate details',
			category: 'crypto',
			recipe_fragment: "#recipe=Parse_X.509_certificate('PEM')",
		},
		{
			name: 'Entropy Analysis',
			description: 'Calculate Shannon entropy to detect encryption/compression',
			category: 'forensic',
			recipe_fragment: "#recipe=Entropy('Shannon%20scale')",
		},
	],
	count: 8,
} satisfies RecipesResponse;

const RECIPES_EMPTY = { recipes: [], count: 0 } satisfies RecipesResponse;

/** TShark ships in the stack, so it is up in every mode. */
const TSHARK_STATUS = {
	available: true,
	version: 'TShark (Wireshark) 4.2.5 (Git v4.2.5 packaged as 4.2.5-1)',
	container_running: true,
	container_name: 'nettap-tshark',
} satisfies TSharkStatus;

// OLD CODE: const MB = 1024 ** 2; (NET-166: named MB, but these are netsniff-ng's MiB)
/** netsniff-ng rotates PCAP files in MiB, so a full 256 MiB file is 268.4 MB on the page. */
const MIB = 1024 ** 2;
const epochSeconds = (msAgo: number): number => (NOW - msAgo) / 1000;

const PCAPS_POPULATED = {
	pcaps: [
		{
			path: '/opt/nettap/pcap/capture_20261103_0900.pcap',
			relative_path: 'capture_20261103_0900.pcap',
			name: 'capture_20261103_0900.pcap',
			size_bytes: 256 * MIB,
			modified: epochSeconds(25 * 60_000),
		},
		{
			path: '/opt/nettap/pcap/capture_20261103_0800.pcap',
			relative_path: 'capture_20261103_0800.pcap',
			name: 'capture_20261103_0800.pcap',
			size_bytes: 256 * MIB,
			modified: epochSeconds(1 * HOUR + 20 * 60_000),
		},
		{
			path: '/opt/nettap/pcap/capture_20261102_2300.pcap',
			relative_path: 'capture_20261102_2300.pcap',
			name: 'capture_20261102_2300.pcap',
			size_bytes: 187 * MIB,
			modified: epochSeconds(1 * DAY),
		},
	],
	count: 3,
} satisfies PcapFilesResponse;

const PCAPS_EMPTY = { pcaps: [], count: 0 } satisfies PcapFilesResponse;

export const TOOLS_ROUTES: FixtureRoute[] = [
	{ path: '/api/cyberchef/status', empty: CYBERCHEF_EMPTY, populated: CYBERCHEF_POPULATED },
	{ path: '/api/cyberchef/recipes', empty: RECIPES_EMPTY, populated: RECIPES_POPULATED },
	{ path: '/api/tshark/status', empty: TSHARK_STATUS },
	{ path: '/api/tshark/pcaps', empty: PCAPS_EMPTY, populated: PCAPS_POPULATED },
];
