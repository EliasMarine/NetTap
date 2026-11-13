/** Every daemon path the visual harness answers. The fixture daemon serves these by pathname. */
import type { FixtureRoute } from './types.ts';
import { ALERT_ROUTES } from './alerts.ts';
import { BANDWIDTH_ROUTES } from './bandwidth.ts';
import { BRIDGE_ROUTES } from './bridge.ts';
import { CAPTURE_ROUTES } from './capture.ts';
import { CERTIFICATE_ROUTES } from './certificates.ts';
import { CHANGELOG_ROUTES } from './changelog.ts';
import { DEVICES_ROUTES } from './devices.ts';
import { DHCP_ROUTES } from './dhcp.ts';
import { DRILLDOWN_ROUTES } from './drilldown.ts';
import { DNS_ROUTES } from './dns.ts';
import { GEOIP_ROUTES } from './geoip.ts';
import { INFRASTRUCTURE_ROUTES } from './infrastructure.ts';
import { INVESTIGATION_ROUTES } from './investigations.ts';
import { IOT_ROUTES } from './iot.ts';
import { LIVE_ROUTES } from './live.ts';
import { LIVE_BANDWIDTH_ROUTES } from './live-bandwidth.ts';
import { LOGS_ROUTES } from './logs.ts';
import { LOOKUP_ROUTES } from './lookup.ts';
import { MOMENT_ROUTES } from './moment.ts';
import { NOTIFICATION_ROUTES } from './notifications.ts';
import { PACKETS_ROUTES } from './packets.ts';
import { PCAP_ROUTES } from './pcap.ts';
import { RISK_ROUTES } from './risk.ts';
import { SETTINGS_ROUTES } from './settings.ts';
import { SETUP_ROUTES } from './setup.ts';
import { STORAGE_ROUTES } from './storage.ts';
import { SURICATA_ROUTES } from './suricata.ts';
import { SURICATA_CATEGORY_ROUTES } from './suricata-category.ts';
import { SYSTEM_ROUTES } from './system.ts';
import { THREAT_ROUTES } from './threats.ts';
import { TOOLS_ROUTES } from './tools.ts';
import { TRAFFIC_ROUTES } from './traffic.ts';
import { UNIFI_ROUTES } from './unifi.ts';

export const ROUTES: readonly FixtureRoute[] = [
	...ALERT_ROUTES,
	...BANDWIDTH_ROUTES,
	...BRIDGE_ROUTES,
	...CAPTURE_ROUTES,
	...CERTIFICATE_ROUTES,
	...CHANGELOG_ROUTES,
	...DEVICES_ROUTES,
	...DHCP_ROUTES,
	...DRILLDOWN_ROUTES,
	...DNS_ROUTES,
	...GEOIP_ROUTES,
	...INFRASTRUCTURE_ROUTES,
	...INVESTIGATION_ROUTES,
	...IOT_ROUTES,
	...LIVE_ROUTES,
	...LIVE_BANDWIDTH_ROUTES,
	...LOGS_ROUTES,
	...LOOKUP_ROUTES,
	...MOMENT_ROUTES,
	...NOTIFICATION_ROUTES,
	...PACKETS_ROUTES,
	...PCAP_ROUTES,
	...RISK_ROUTES,
	...SETTINGS_ROUTES,
	...SETUP_ROUTES,
	...STORAGE_ROUTES,
	...SURICATA_ROUTES,
	...SURICATA_CATEGORY_ROUTES,
	...SYSTEM_ROUTES,
	...THREAT_ROUTES,
	...TOOLS_ROUTES,
	...TRAFFIC_ROUTES,
	...UNIFI_ROUTES,
];
