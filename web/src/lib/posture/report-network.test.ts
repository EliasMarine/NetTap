import { describe, it, expect } from 'vitest';
import { EMPTY_DATA, scoreCategories, type PostureInputs, type PostureSlug } from './score';
import type { ExtraKey, PostureExtras, ReportData } from './report';
import { alertReport, monitoringReport, segmentationReport, MIRROR_NOTE } from './report-network';
import { BRIDGE_NO_DEVICES, type CaptureStatsResponse } from '$api/capture';
import type { NetworkIsolation } from '$api/iot';
import type { SystemHealth } from '$api/system';
import type { DeviceRiskScore } from '$api/risk';

const WIN = { from: '2026-11-15T06:00:00.000Z', to: '2026-11-16T06:00:00.000Z' };
function reportData(slug: PostureSlug, o: { inputs?: Partial<PostureInputs>; extras?: PostureExtras; failed?: ExtraKey[]; names?: Map<string, string> } = {}): ReportData {
	const inputs: PostureInputs = { ...EMPTY_DATA, failed: [], health: { health: null, failed: false }, ...o.inputs };
	return { window: WIN, inputs, category: scoreCategories(inputs).find((c) => c.slug === slug)!, extras: o.extras ?? {}, failed: o.failed ?? [], names: o.names ?? new Map() };
}
const score = (ip: string, over: Partial<DeviceRiskScore> = {}): DeviceRiskScore => ({ ip, score: 10, level: 'low', factors: [], ...over });
const devices = (seen: number, scored: number): Partial<PostureInputs> => ({
	deviceCount: { from: '', to: '', count: seen },
	riskScores: { scores: Array.from({ length: scored }, (_, i) => score(`192.168.1.${i + 2}`)) },
});
const ISOLATION: NetworkIsolation = {
	segmentation_score: 70,
	segmentation_grade: 'C',
	recommendation: 'Put smart devices on their own network.',
	pairs: [
		{ iot_device: { mac: '02:00:5e:10:00:50', name: 'Camera', ip: '192.168.1.50' }, internal_target: { ip: '192.168.1.20', hostname: null }, risk: 'high', connection_count: 40, ports: [80, 445], reached: true, reached_ports: [80], description: 'Camera can reach 192.168.1.20 via HTTP' },
		{ iot_device: { mac: '02:00:5e:10:00:31', name: 'Thermostat', ip: '192.168.1.31' }, internal_target: { ip: '192.168.1.6', hostname: null }, risk: 'low', connection_count: 2, ports: [], reached: true, reached_ports: [], description: 'Thermostat can reach 192.168.1.6 via ping (ICMP)' },
		{ iot_device: { mac: '02:00:5e:10:00:60', name: 'Plug', ip: '192.168.1.60' }, internal_target: { ip: '192.168.1.20', hostname: null }, risk: 'critical', connection_count: 9, ports: [22], reached: false, reached_ports: [], description: 'Plug sent traffic to 192.168.1.20 via SSH; reachability not confirmed (no data seen both ways)' },
	],
};
const health = (state: string, sensors: Record<string, string> = {}): PostureInputs['health'] => ({
	health: { pipeline: { state, newest_record_at: null, age_seconds: 1200, threshold_seconds: 900, sensors, checked_at: '' } } as unknown as SystemHealth,
	failed: false,
});
const stats = (lost: number, arrived = 100_000): CaptureStatsResponse =>
	({ loss_window: { state: 'ok', interface: 'enp1s0', window: { arrived, lost, drop_rate_pct: (lost / arrived) * 100, seconds: 3600 }, cumulative: null } }) as unknown as CaptureStatsResponse;

// OLD CODE START — NET-308: segmentation scored baselines; isolation was an extra
// describe('segmentationReport', () => { … baseline source, "100 − 10 × …" formula, isolation extra … });
// OLD CODE END
describe('segmentationReport', () => {
	const seg = (o: Parameters<typeof reportData>[1] = {}) => segmentationReport(reportData('network-segmentation', o));

	it('scores reached pairs only, and lists an unconfirmed one as its own finding', () => {
		const r = seg({ inputs: { isolation: ISOLATION }, names: new Map([['192.168.1.20', 'Laptop']]) });
		const [camera, plug] = [r.findings.find((f) => f.key.includes('192.168.1.50'))!, r.findings.find((f) => f.key.includes('192.168.1.60'))!];
		expect(camera).toMatchObject({ severity: 'high', title: 'Camera reached another device on your network', count: 40, devices: [{ ip: '192.168.1.50' }, { ip: '192.168.1.20', name: 'Laptop' }] });
		expect(camera.detail).toBe('Camera can reach 192.168.1.20 via HTTP Ports: 80.');
		// review L4: not confirmed to get through, so low whatever its ports' risk (critical here)
		expect(plug).toMatchObject({ severity: 'low', title: 'Reachability not confirmed' });
		expect(plug.fix).toMatch(/couldn’t tell whether it got through/);
		expect(r.steps[0]).toEqual({ priority: 'high', text: 'Move Camera to a guest or IoT network: it reached Laptop.' });
		expect(r.steps.filter((x) => x.priority === 'high')).toHaveLength(1); // the unconfirmed plug is no high step
		expect(r.kpis.map((k) => [k.label, k.value])).toEqual([['Score', '70'], ['Smart devices reaching others', '2'], ['Reachability not confirmed', '1']]);
		expect(r.kpis[1].sub).toBe('isolation 70/100, grade C');
		expect(r.drivers.formula).toBe('100 − 25 × 0 critical − 15 × 1 high − 5 × 0 medium reached pairs = 70 (pings, low-risk pairs and pairs whose reachability isn’t confirmed cost nothing)');
		expect(r.drivers.bars.map((b) => [b.key, b.value])).toEqual([['critical', 0], ['high', 1], ['medium', 0], ['low', 1], ['unconfirmed', 1]]);
		expect(r.drivers.limits).toEqual([
			'It only sees traffic that passes NetTap; two devices on the same switch or access point can talk without it.',
			'A device counts as smart (IoT) by its maker; one NetTap doesn’t recognise isn’t checked.',
			'A connection counts as reaching a device only if data went both ways; a bare TCP handshake with no data doesn’t count.',
		]);
		expect(r.drivers.counts.join(' ')).toContain('Put smart devices on their own network.');
	});

	it('reads Not measured with no smart devices, and no baseline finding any more', () => {
		const r = seg({ inputs: { ...devices(6, 4), isolation: { ...ISOLATION, segmentation_score: null, segmentation_grade: null, pairs: [] } } });
		expect(r.sources.map((x) => [x.key, x.state])).toEqual([['isolation', 'not-measured']]);
		expect(r.sources[0].note).toMatch(/^No smart \(IoT\) devices detected yet · Data pipeline now:/);
		expect(r.kpis[1]).toMatchObject({ value: 'Not measured' });
		expect(r.findings).toEqual([]);
	});

	it("reads a failed isolation request as failed, never as a 100", () => {
		const r = seg({ inputs: { failed: ['isolation'], isolation: { ...ISOLATION, segmentation_score: 100 } } });
		expect(r.sources.map((x) => x.state)).toEqual(['failed']);
		expect(r.kpis[0].value).toBe('—');
		expect(r.kpis[1]).toMatchObject({ value: '—', sub: "Couldn't load" });
		expect(r.findings).toEqual([]);
	});

	it('shows no stand-in "0 of 0" on Monitoring coverage when the device count failed (review M2)', () => {
		const m = monitoringReport(reportData('monitoring-coverage', { inputs: { failed: ['devices'], health: health('fresh') }, extras: { mode: { mode: 'mirror', interface: 'x' }, stats: stats(0) } }));
		expect(m.kpis[1]).toMatchObject({ key: 'scored', value: '—', sub: "Couldn't load" });
	});
});

describe('rule links', () => {
	it("open main's rule page over the snapshot window, and the Alerts list for rows with no rule name (R2-4)", () => {
		const sigs = { from: WIN.from, to: WIN.to, complete: true, examined: 4, signatures: [
			{ signature: 'ET INFO Spotify P2P Client', count: 5, severity: 3 },
			{ signature: 'a/b?c', count: 4, severity: 2 },
			{ signature: null, count: 3, severity: 2 },
			{ signature: '', count: 2, severity: 2 },
		] };
		const r = alertReport(reportData('alert-response', { inputs: { alertCounts: { from: '', to: '', counts: { total: 14, high: 0, medium: 9, low: 5 } } }, extras: { signatures: sigs } }));
		const [spotify, slash, none, empty] = r.findings.filter((f) => f.key.startsWith('rule-')).sort((a, b) => b.count! - a.count!).map((f) => f.href!);
		expect(spotify.startsWith('/alerts/rule/ET%20INFO%20Spotify%20P2P%20Client?')).toBe(true);
		expect(Object.fromEntries(new URL(spotify, 'http://x').searchParams)).toEqual({ ...WIN, range: '24h' });
		expect(slash).toMatch(/^\/alerts\/rule\/a%2Fb%3Fc\?/);
		expect(none).toMatch(/^\/alerts\?no_rule_name=true&/);
		expect(empty).toMatch(/^\/alerts\?signature=&/);
	});
});

// OLD CODE START — NET-308: investigation status (all time) against 24 hours of alerts
// describe('alertReport', () => { … "757 alerts and no investigations, so the score is 0.", "Investigations (all time)" … });
// OLD CODE END
describe('alertReport', () => {
	const ALERTS: Partial<PostureInputs> = { alertCounts: { from: '', to: '', counts: { total: 757, high: 295, medium: 219, low: 243 } } };
	const SIGS = {
		from: WIN.from,
		to: WIN.to,
		complete: true,
		examined: 3,
		signatures: [
			{ signature: 'IPFire DBL Phishing DNS', count: 266, severity: 1 },
			{ signature: 'ET INFO Spotify P2P Client', count: 235, severity: 3 },
			{ signature: null, count: 4, severity: 2 },
		],
	};
	const RESPONSE = {
		...EMPTY_DATA.alertResponse,
		from: WIN.from,
		to: WIN.to,
		needing: 3,
		investigated: 1,
		groups: [
			{ rule: 'IPFire DBL Phishing DNS', count: 266, investigated: false },
			{ rule: null, count: 2, investigated: false },
			{ rule: 'ET SCAN Nmap', count: 5, investigated: true },
		],
		investigations: { open_during: 1, linked_alerts: 1, unresolved_links: 0, skipped: 0 },
	};
	const alerts = (o: Parameters<typeof reportData>[1] = {}) => alertReport(reportData('alert-response', o));

	it('lists each high-severity rule, an uninvestigated one high and linked to its Alerts list', () => {
		const r = alerts({ inputs: { ...ALERTS, alertResponse: RESPONSE }, extras: { signatures: SIGS } });
		const dbl = r.findings.find((f) => f.key === 'group-0')!;
		expect(dbl).toMatchObject({ severity: 'high', title: 'IPFire DBL Phishing DNS', count: 266, fix: 'Open one of its alerts and choose Open an investigation.' });
		expect(dbl.href).toMatch(/^\/alerts\?signature=IPFire\+DBL\+Phishing\+DNS&/);
		expect(r.findings.find((f) => f.key === 'group-1')).toMatchObject({ title: 'Alerts with no rule name', severity: 'high' });
		expect(r.findings.find((f) => f.key === 'group-1')!.href).toMatch(/no_rule_name=true/);
		expect(r.findings.find((f) => f.key === 'group-2')).toMatchObject({ severity: 'info', title: 'ET SCAN Nmap' });
		// the busiest rules that aren't high still show; the high one is listed once, as a group
		expect(r.findings.filter((f) => f.title === 'IPFire DBL Phishing DNS')).toHaveLength(1);
		expect(r.findings.find((f) => f.title === 'ET INFO Spotify P2P Client')!.fix).toBe('Review it; it is often expected activity.');
		expect(r.kpis.map((k) => [k.label, k.value])).toEqual([['Score', '33'], ['Rules that needed a response', '1 of 3'], ['Alerts', '757']]);
		expect(r.drivers.formula).toBe('1 with an investigation ÷ 3 high-severity rules = 33%');
		expect(r.drivers.counts[1]).toBe('Investigations open at some point in the last 24 hours: 1, linking 1 alerts.');
		expect(r.drivers.bars.map((b) => [b.label, b.value])).toEqual([['With an investigation', 1], ['Without an investigation', 2]]);
	});

	it('asks for an investigation from the alert for each rule without one, never from the Investigations page', () => {
		const r = alerts({ inputs: { ...ALERTS, alertResponse: RESPONSE }, extras: { signatures: SIGS } });
		expect(r.steps[0]).toEqual({
			priority: 'high',
			text: 'Open an investigation for each of the 2 high-severity rules without one: open one of its alerts and choose Open an investigation. An investigation made on the Investigations page links no alert, so it doesn’t count.',
		});
		const review = r.steps.find((x) => x.priority === 'low')!;
		expect(review.text).toContain('Volume alone is never a reason.');
	});

	it('says plainly that links made before this change don\'t count, and how to count the rule (R5)', () => {
		const old = { ...RESPONSE, investigations: { ...RESPONSE.investigations, unresolved_links: 3, skipped: 1 } };
		const r = alerts({ inputs: { ...ALERTS, alertResponse: old }, extras: { signatures: SIGS } });
		expect(r.drivers.counts).toContain(
			'3 alerts linked before this change can’t be matched to a rule, so they don’t count. To count a rule, open an investigation from one of its alerts.',
		);
		expect(r.drivers.counts).toContain('1 investigation record(s) couldn’t be read, so they don’t count.');
		expect(r.drivers.counts.join(' ')).not.toMatch(/from the alert/);
		// plain English: no API instructions on the page
		expect([...r.drivers.counts, ...r.drivers.limits].join(' ')).not.toMatch(/\/api\/|endpoint|POST/);
		expect(r.drivers.limits).toContain('NetTap keeps no close time, so a closed investigation counts until its last change; a note added after closing keeps it counting.');
		expect(r.drivers.limits).not.toContain('Investigations count all time; alerts count the last 24 hours.');
	});

	it('notes when only the first 25 of the rules are listed', () => {
		const many = { ...RESPONSE, needing: 40, investigated: 0, groups: Array.from({ length: 25 }, (_, i) => ({ rule: `ET R${i}`, count: 1, investigated: false })) };
		const r = alerts({ inputs: { ...ALERTS, alertResponse: many }, extras: { signatures: SIGS } });
		expect(r.notes).toEqual([{ text: 'Showing 25 of the 40 high-severity rules, the ones without an investigation first.' }]);
	});

	it('adds devices whose own traffic matched rules', () => {
		const inputs = {
			...ALERTS,
			alertResponse: RESPONSE,
			riskScores: { scores: [score('192.168.1.44', { level: 'high', alert_count: 12, factors: [{ name: 'alert_count', score: 30, max: 40, description: '12 alerts, 2 high' }] })] },
		};
		const r = alerts({ inputs, extras: { signatures: SIGS } });
		expect(r.findings.find((f) => f.key === 'device-192.168.1.44')).toMatchObject({ severity: 'high', count: 12, detail: '12 alerts: 12 alerts, 2 high.' });
	});

	it('reads nothing needing a response as not measured, and a failed follow-up request as failed', () => {
		const quiet = alerts({ inputs: ALERTS, extras: { signatures: { ...SIGS, signatures: [] } } });
		expect(quiet.sources[0]).toMatchObject({ key: 'response', state: 'not-measured' });
		expect(quiet.sources[0].note).toMatch(/^Nothing needed a response in the last 24 hours · /);
		expect(quiet.steps).toEqual([]);
		const failed = alerts({ inputs: { ...ALERTS, failed: ['response'] }, extras: { signatures: SIGS } });
		expect(failed.sources[0].state).toBe('failed');
		expect(failed.kpis[1]).toMatchObject({ value: '—', sub: "Couldn't load" });
		expect(alerts({ inputs: ALERTS, failed: ['signatures'] }).sources[1].state).toBe('failed');
	});
});

describe('monitoringReport', () => {
	it('shows a stopped sensor and the capture mode even with no devices seen (R2-1)', () => {
		const r = monitoringReport(reportData('monitoring-coverage', { inputs: { health: health('sensor_stopped', { 'nettap-zeek-live': 'exited' }) }, extras: { mode: { mode: 'bridge', interface: 'br0' }, stats: stats(0) } }));
		expect(r.sources.map((s) => [s.key, s.state])).toEqual([['baseline', 'not-measured'], ['pipeline', 'measured'], ['loss', 'measured'], ['mode', 'measured']]);
		expect(r.findings.find((f) => f.key === 'pipeline')).toMatchObject({ severity: 'high', title: 'Data pipeline: Zeek stopped', href: '/system' });
		expect(r.findings.find((f) => f.key === 'mode')).toMatchObject({ severity: 'medium', detail: BRIDGE_NO_DEVICES });
		expect(r.kpis[2]).toMatchObject({ value: 'Failing', sub: 'Zeek stopped' });
	});

	it('flags packet loss over 0.1 %, and notes what a mirror port can miss', () => {
		const r = monitoringReport(reportData('monitoring-coverage', { inputs: { ...devices(10, 8), health: health('fresh') }, extras: { mode: { mode: 'mirror', interface: 'enp2s0' }, stats: stats(500) } }));
		expect(r.findings.find((f) => f.key === 'loss')).toMatchObject({ severity: 'high', href: '/infrastructure' });
		expect(r.findings.find((f) => f.key === 'mode')).toMatchObject({ severity: 'info', detail: MIRROR_NOTE });
		expect(r.findings.find((f) => f.key === 'unscored')).toMatchObject({ count: 2 });
		expect(r.drivers.formula).toBe('8 devices with a risk score ÷ 10 devices seen = 80%');
	});

	it('marks each failed request on its own source', () => {
		const r = monitoringReport(reportData('monitoring-coverage', { inputs: { ...devices(2, 2), health: { health: null, failed: true } }, failed: ['mode', 'stats'] }));
		expect(r.sources.map((s) => s.state)).toEqual(['measured', 'failed', 'failed', 'failed']);
		expect(r.findings).toEqual([]);
	});
});
