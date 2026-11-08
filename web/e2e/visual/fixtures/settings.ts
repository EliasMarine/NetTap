import type { FixtureRoute } from './types.ts';

/** GET /api/settings/api-keys: which keys are set. The daemon never returns the values. */
interface ApiKeysResponse {
	keys: Record<string, boolean>;
}

/** GET /api/settings/excluded-ips: the addresses left out of the device views. */
interface ExcludedIpsResponse {
	excluded_ips: string[];
}

const KEYS_EMPTY = {
	keys: {
		MAXMIND_LICENSE_KEY: false,
		SMTP_HOST: false,
		SMTP_PORT: false,
		SMTP_USERNAME: false,
		SMTP_PASSWORD: false,
		SMTP_SENDER_EMAIL: false,
		WEBHOOK_URL: false,
		// OLD CODE START — NET-191 slice 2: the daemon no longer has this key (the ET Pro code is in Settings › Suricata rules)
		// SURICATA_ET_PRO_KEY: false,
		// OLD CODE END
	},
} satisfies ApiKeysResponse;

const KEYS_POPULATED = { keys: { ...KEYS_EMPTY.keys, MAXMIND_LICENSE_KEY: true } } satisfies ApiKeysResponse;

const EXCLUDED_EMPTY = { excluded_ips: [] } satisfies ExcludedIpsResponse;

// The appliance's own management address and the household's public address.
const EXCLUDED_POPULATED = { excluded_ips: ['192.168.1.50', '203.0.113.45'] } satisfies ExcludedIpsResponse;

/** GET /api/settings/home-location: where the network is, for the Live globe. */
interface HomeLocationResponse {
	home: { lat: number; lon: number; label: string } | null;
}

const HOME_EMPTY = { home: null } satisfies HomeLocationResponse;
const HOME_POPULATED = { home: { lat: 51.5074, lon: -0.1278, label: 'London' } } satisfies HomeLocationResponse;

// `method` because both paths also take a POST/PUT with a different body.
export const SETTINGS_ROUTES: FixtureRoute[] = [
	{ path: '/api/settings/home-location', method: 'GET', empty: HOME_EMPTY, populated: HOME_POPULATED },
	{ path: '/api/settings/api-keys', method: 'GET', empty: KEYS_EMPTY, populated: KEYS_POPULATED },
	{ path: '/api/settings/excluded-ips', method: 'GET', empty: EXCLUDED_EMPTY, populated: EXCLUDED_POPULATED },
];
