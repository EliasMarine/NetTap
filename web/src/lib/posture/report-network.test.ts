import { describe, it, expect } from 'vitest';
import { EMPTY_DATA, scoreCategories, type PostureInputs, type PostureSlug } from './score';
import type { ExtraKey, PostureExtras, ReportData } from './report';
import { alertReport, monitoringReport, postureRuleHref, segmentationReport, MIRROR_NOTE } from './report-network';
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
		{ iot_device: { mac: '02:00:5e:10:00:50', name: 'Camera', ip: '192.168.1.50' }, internal_target: { ip: '192.168.1.20', hostname: null }, risk: 'high', connection_count: 40, ports: [445], description: 'Camera reached a computer on port 445.' },
		{ iot_device: { mac: '02:00:5e:10:00:31', name: 'Thermostat', ip: '192.168.1.31' }, internal_target: { ip: '192.168.1.6', hostname: null }, risk: 'low', connection_count: 2, ports: [], description: 'Thermostat pinged a server.' },
	],
};
const health = (state: string, sensors: Record<string, string> = {}): PostureInputs['health'] => ({
	health: { pipeline: { state, newest_record_at: null, age_seconds: 1200, threshold_seconds: 900, sensors, checked_at: '' } } as unknown as SystemHealth,
	failed: false,
});
const stats = (lost: number, arrived = 100_000): CaptureStatsResponse =>
	({ loss_window: { state: 'ok', interface: 'enp1s0', window: { arrived, lost, drop_rate_pct: (lost / arrived) * 100, seconds: 3600 }, cumulative: null } }) as unknown as CaptureStatsResponse;

describe('segmentationReport', () => {
	it('lists each isolation pair with both addresses, and steps high pairs up', () => {
		const r = segmentationReport(reportData('network-segmentation', { inputs: devices(5, 5), extras: { isolation: ISOLATION }, names: new Map([['192.168.1.20', 'Laptop']]) }));
		const pair = r.findings[0];
		expect(pair).toMatchObject({ severity: 'high', count: 40, devices: [{ ip: '192.168.1.50' }, { ip: '192.168.1.20', name: 'Laptop' }] });
		expect(pair.detail).toContain('Ports: 445.');
		expect(r.steps[0]).toEqual({ priority: 'high', text: 'Move Camera to a guest or IoT network: it reached Laptop.' });
		expect(r.steps.at(-1)!.priority).toBe('low');
		expect(r.drivers.counts.join(' ')).toContain('smart-device isolation 70/100 (grade C). Put smart devices on their own network.');
		expect(r.drivers.limits[0]).toMatch(/not whether your network is split into zones/);
	});

	it('marks only isolation not measured when there are no smart devices, and keeps the baseline findings (R2-1)', () => {
		const r = segmentationReport(reportData('network-segmentation', { inputs: devices(6, 4), extras: { isolation: { ...ISOLATION, segmentation_score: null, segmentation_grade: null, pairs: [] } } }));
		expect(r.sources.map((s) => [s.key, s.state])).toEqual([['baseline', 'measured'], ['isolation', 'not-measured']]);
		expect(r.sources[1].note).toMatch(/^No smart \(IoT\) devices detected yet · Data pipeline now:/);
		expect(r.kpis[2]).toMatchObject({ value: 'Not measured' });
		expect(r.findings).toEqual([expect.objectContaining({ key: 'unscored', count: 2, href: '/devices' })]);
		expect(r.drivers.formula).toBe('100 − 10 × 2 device(s) without a baseline = 80');
	});

	it('keeps the baseline source when the isolation request failed', () => {
		const r = segmentationReport(reportData('network-segmentation', { inputs: devices(3, 3), failed: ['isolation'] }));
		expect(r.sources.map((s) => s.state)).toEqual(['measured', 'failed']);
		expect(r.kpis[2]).toMatchObject({ value: '—' });
	});

	it('shows no stand-in "0 of 0" when the device count or risk scores failed (review M2)', () => {
		const r = segmentationReport(reportData('network-segmentation', { inputs: { failed: ['risk'] }, extras: { isolation: ISOLATION } }));
		expect(r.kpis[1]).toMatchObject({ key: 'baseline', value: '—', sub: "Couldn't load" });
		expect(r.findings.length).toBe(2);
		const m = monitoringReport(reportData('monitoring-coverage', { inputs: { failed: ['devices'], health: health('fresh') }, extras: { mode: { mode: 'mirror', interface: 'x' }, stats: stats(0) } }));
		expect(m.kpis[1]).toMatchObject({ key: 'scored', value: '—', sub: "Couldn't load" });
	});
});

describe('postureRuleHref', () => {
	it('opens the rule page over the snapshot window, and the Alerts list for rows with no rule name (R2-4)', () => {
		const href = postureRuleHref('ET INFO Spotify P2P Client', WIN);
		expect(href.startsWith('/alerts/rule/ET%20INFO%20Spotify%20P2P%20Client?')).toBe(true);
		expect(Object.fromEntries(new URL(href, 'http://x').searchParams)).toEqual({ ...WIN, range: '24h' });
		expect(postureRuleHref('a/b?c', WIN)).toMatch(/^\/alerts\/rule\/a%2Fb%3Fc\?/);
		expect(postureRuleHref(null, WIN)).toMatch(/^\/alerts\?no_rule_name=true&/);
		expect(postureRuleHref('', WIN)).toMatch(/^\/alerts\?signature=&/);
	});
});

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

	it('asks for an investigation when there are alerts and none was opened, and reviews informational rules without suppressing by volume (R1-4)', () => {
		const r = alertReport(reportData('alert-response', { inputs: ALERTS, extras: { signatures: SIGS } }));
		expect(r.drivers.formula).toBe('757 alerts and no investigations, so the score is 0.');
		expect(r.steps[0]).toMatchObject({ priority: 'high', href: '/investigations' });
		const review = r.steps.find((s) => s.priority === 'low')!;
		expect(review.text).toContain('Only once you have confirmed the activity is expected');
		expect(review.text).toContain('Volume alone is never a reason.');
		const info = r.findings.find((f) => f.title === 'ET INFO Spotify P2P Client')!;
		expect(info.fix).toBe('Review it; it is often expected activity.');
		expect(r.findings.find((f) => f.title === 'IPFire DBL Phishing DNS')).toMatchObject({ severity: 'high', fix: 'Check the devices it involved today.' });
		expect(r.findings.find((f) => f.title === 'Alerts with no rule name')!.href).toMatch(/no_rule_name=true/);
	});

	it('labels investigations all time, and adds devices whose own traffic matched rules', () => {
		const inputs = {
			...ALERTS,
			investigationStats: { total: 4, by_status: { open: 1, resolved: 2, closed: 1 }, by_severity: {} },
			riskScores: { scores: [score('192.168.1.44', { level: 'high', alert_count: 12, factors: [{ name: 'alert_count', score: 30, max: 40, description: '12 alerts, 2 high' }] })] },
		};
		const r = alertReport(reportData('alert-response', { inputs, extras: { signatures: SIGS } }));
		expect(r.kpis[2]).toMatchObject({ label: 'Investigations (all time)', value: '3 of 4' });
		expect(r.drivers.formula).toBe('3 resolved or closed ÷ 4 investigations = 75%');
		expect(r.drivers.limits).toContain('Investigations count all time; alerts count the last 24 hours.');
		expect(r.steps.map((s) => s.priority)).toEqual(['medium', 'low']);
		expect(r.findings.find((f) => f.key === 'device-192.168.1.44')).toMatchObject({ severity: 'high', count: 12, detail: '12 alerts: 12 alerts, 2 high.' });
	});

	it('reads no counted alerts as not measured with the pipeline state, and a failed list as failed', () => {
		const quiet = alertReport(reportData('alert-response', { extras: { signatures: { ...SIGS, signatures: [] } } }));
		expect(quiet.sources[0]).toMatchObject({ state: 'not-measured' });
		expect(quiet.steps).toEqual([]);
		const failed = alertReport(reportData('alert-response', { inputs: ALERTS, failed: ['signatures'] }));
		expect(failed.sources[0].state).toBe('failed');
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
