/**
 * NET-316: the Devices table as CSV, in raw units (bytes, ISO times) for a spreadsheet.
 * Every cell goes through csvCell, because hostnames come from the network and could be formulas.
 */
import type { Device } from '$lib/api/devices';
import { csvCell } from '$lib/utils/csv';
import { isPrivateMac } from '$lib/utils/mac';

/**
 * The name the network gave the device. With an owner's name, `hostname` already holds that name
 * (device_custom.present), so the network's one is `discovered_name`; its null stays blank.
 */
const discoveredName = (d: Device) => (d.custom_name ? d.discovered_name : d.hostname) ?? null;

const privateMac = (d: Device) => (d.mac ? (isPrivateMac(d.mac) ? 'yes' : 'no') : null);

type CsvColumn = readonly [string, (d: Device, status: (d: Device) => string) => unknown];

const COLUMNS: readonly CsvColumn[] = [
	['IP address', (d) => d.ip],
	['MAC address', (d) => d.mac],
	['Private MAC', privateMac],
	['Name', (d) => d.custom_name ?? d.unifi_name ?? d.hostname],
	['Discovered name', discoveredName],
	['Status', (d, status) => status(d)],
	['Type', (d) => d.category ?? 'unknown'],
	['OS', (d) => d.os_hint],
	['Manufacturer', (d) => d.manufacturer],
	['Total bytes', (d) => d.total_bytes],
	['Upload bytes', (d) => d.upload_bytes],
	['Download bytes', (d) => d.download_bytes],
	['Connections', (d) => d.connection_count],
	['Alerts', (d) => d.alert_count],
	['Last seen', (d) => d.last_seen || null],
];

/** The rows as CSV, header first; `status` is the table's own Status word for a row. */
export function toDevicesCsv(rows: readonly Device[], status: (d: Device) => string): string {
	const head = COLUMNS.map(([label]) => csvCell(label)).join(',');
	return [head, ...rows.map((d) => COLUMNS.map(([, value]) => csvCell(value(d, status))).join(','))].join('\n');
}
