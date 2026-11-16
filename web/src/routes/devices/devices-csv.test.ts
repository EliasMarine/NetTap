import { describe, expect, it } from 'vitest';
import type { Device } from '$lib/api/devices';
import { toDevicesCsv } from './devices-csv';

const BASE: Device = {
	ip: '192.168.1.10', mac: 'bc:24:11:00:00:01', hostname: 'laptop', manufacturer: 'Proxmox', os_hint: 'Linux',
	first_seen: '2026-11-16T10:00:00.000Z', last_seen: '2026-11-16T12:00:00.000Z', total_bytes: 3000,
	upload_bytes: 1000, download_bytes: 2000, connection_count: 42, protocols: ['tcp'], alert_count: 1, category: 'computer',
	services: ['ssl', 'dns'], known_since: '2026-10-01T08:00:00.000Z',
};

const live = () => 'Online';
const lines = (rows: Device[], status = live) => toDevicesCsv(rows, status).split('\n');

describe('toDevicesCsv', () => {
	it('starts with the header', () => {
		expect(lines([])).toEqual([
			'"IP address","MAC address","Private MAC","Name","Discovered name","Status","Type","OS","Manufacturer","Total bytes","Upload bytes","Download bytes","Connections","Alerts","Protocols","First seen","Last seen"',
		]);
	});

	it('writes a row in raw units', () => {
		expect(lines([BASE])[1]).toBe(
			'"192.168.1.10","bc:24:11:00:00:01","no","laptop","laptop","Online","computer","Linux","Proxmox",3000,1000,2000,42,1,"ssl dns","2026-10-01T08:00:00.000Z","2026-11-16T12:00:00.000Z"',
		);
	});

	it("gives a renamed device its owner's name and, apart, the network's name", () => {
		const renamed = { ...BASE, hostname: 'Work laptop', custom_name: 'Work laptop', discovered_name: 'eli-mbp' };
		const cells = lines([renamed])[1].split(',');
		expect(cells[3]).toBe('"Work laptop"');
		expect(cells[4]).toBe('"eli-mbp"');
		// a renamed device the network never named: blank, not the alias twice
		const unnamed = lines([{ ...renamed, discovered_name: null }])[1].split(',');
		expect(unnamed[4]).toBe('');
	});

	it('leaves missing values blank and passes the Status word through', () => {
		const sparse: Device = {
			...BASE, mac: null, hostname: null, manufacturer: null, os_hint: null, category: undefined,
			upload_bytes: undefined, download_bytes: undefined, last_seen: '', services: null, known_since: null,
		};
		expect(lines([sparse], () => '—')[1]).toBe('"192.168.1.10",,,,,"—","unknown",,,3000,,,42,1,,,');
		// none identified exports blank too, as does an older daemon's row without the fields
		expect(lines([{ ...sparse, services: [] }], () => '—')[1]).toBe(lines([sparse], () => '—')[1]);
		expect(lines([{ ...sparse, services: undefined, known_since: undefined }], () => '—')[1]).toBe(lines([sparse], () => '—')[1]);
	});

	it('marks a private MAC', () => {
		expect(lines([{ ...BASE, mac: 'da:a1:19:00:00:01' }])[1].split(',')[2]).toBe('"yes"');
	});

	it('makes a formula-looking name literal and keeps quotes and commas inside one cell', () => {
		const row = lines([{ ...BASE, hostname: '=HYPERLINK("http://x","y")' }])[1];
		expect(row).toContain('"\'=HYPERLINK(""http://x"",""y"")"');
		const comma = toDevicesCsv([{ ...BASE, hostname: 'a, "b"' }], live);
		expect(comma).toContain('"a, ""b"""');
	});
});
