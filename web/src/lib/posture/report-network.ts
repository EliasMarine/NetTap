/**
 * The device and system categories' reports: Network segmentation, Alert response and Monitoring
 * coverage. Each source (isolation, top rules, the pipeline, packet loss, capture mode) is judged on
 * its own, so one that saw nothing or failed leaves the others' findings in place.
 */
import { BRIDGE_NO_DEVICES, lossWords } from '$api/capture';
import { pipelineStage } from '$api/system';
import { alertsHrefForSignature, fmt, windowQuery } from '$lib/utils/drilldown';
import { suricataLevel, type SeverityLevel } from '$lib/utils/severity';
import { listWords } from '$api/system';
import { device, deviceWords, failedSource, notMeasured, scoreKpi, unloaded, type Finding, type Kpi, type Report, type ReportData, type Source, type Step } from './report';

/** Devices with a baseline: the score's own figures (min() as the score takes it). */
function baselineCounts(data: ReportData): { total: number; scored: number; unscored: number } {
	const total = data.inputs.deviceCount.count;
	const scored = Math.min(data.inputs.riskScores.scores.length, total);
	return { total, scored, unscored: total - scored };
}

/** The baseline source both device categories read. */
function baselineSource(data: ReportData, label: string): Source {
	const failed = data.inputs.failed.filter((f) => f === 'devices' || f === 'risk');
	if (failed.length) return failedSource('baseline', label);
	if (data.inputs.deviceCount.count === 0) return notMeasured('baseline', label, 'No devices seen in the last 24 hours', data.inputs);
	return { key: 'baseline', label, state: 'measured' };
}

function unscoredFinding(unscored: number, what: string): Finding {
	return {
		key: 'unscored',
		severity: 'medium',
		title: `${fmt(unscored)} device(s) without ${what}`,
		detail: 'NetTap scores a device once it has seen enough of its traffic; a new device usually gets one within a day.',
		devices: [],
		count: unscored,
		fix: 'Leave NetTap running; if a device stays unscored for days, look it up on the Devices page.',
		href: '/devices',
	};
}

// --- Network segmentation ---

/** The daemon's risk words (isolation pairs, device risk levels) as severity levels */
const RISK_LEVEL: Record<string, SeverityLevel> = { critical: 'critical', high: 'high', medium: 'medium', low: 'low' };

export function segmentationReport(data: ReportData): Report {
	const { category, names } = data;
	const b = baselineCounts(data);
	const iso = data.extras.isolation;
	const isoFailed = data.failed.includes('isolation') || !iso;
	const isoMeasured = !isoFailed && iso.segmentation_score !== null;

	const sources: Source[] = [
		baselineSource(data, 'Device baselines'),
		isoFailed
			? failedSource('isolation', 'Smart-device isolation')
			: isoMeasured
				? { key: 'isolation', label: 'Smart-device isolation', state: 'measured' }
				: notMeasured('isolation', 'Smart-device isolation', 'No smart (IoT) devices detected yet', data.inputs),
	];

	const pairs = isoMeasured ? iso.pairs : [];
	const findings: Finding[] = pairs.map((p, i) => ({
		key: `pair-${i}-${p.iot_device.ip}-${p.internal_target.ip}`,
		severity: RISK_LEVEL[p.risk.toLowerCase()] ?? 'medium',
		title: `${p.iot_device.name || p.iot_device.ip} reached another device on your network`,
		detail: `${p.description}${p.ports.length ? ` Ports: ${listWords(p.ports.map(String))}.` : ''}`,
		devices: [device(p.iot_device.ip, names), device(p.internal_target.ip, names)],
		count: p.connection_count,
		fix: 'Move smart devices to a guest or IoT network and turn on client isolation, so they can’t reach your computers.',
	}));
	if (sources[0].state === 'measured' && b.unscored > 0) findings.push(unscoredFinding(b.unscored, 'a baseline'));

	const serious = pairs.filter((p) => ['critical', 'high'].includes(p.risk.toLowerCase()));
	const medium = pairs.filter((p) => p.risk.toLowerCase() === 'medium');
	const steps: Step[] = [
		...serious.map((p) => ({ priority: 'high' as const, text: `Move ${p.iot_device.name || p.iot_device.ip} to a guest or IoT network: it reached ${deviceWords(p.internal_target.ip, names)}.` })),
		...(medium.length ? [{ priority: 'medium' as const, text: `${medium.length} more smart device connection(s) to your other devices: check them in Findings and move those devices to a guest network.` }] : []),
		...(sources[0].state === 'measured' && b.unscored > 0 ? [{ priority: 'medium' as const, text: `${fmt(b.unscored)} device(s) have no baseline yet; leave NetTap running and check them on the Devices page.`, href: '/devices' }] : []),
		...(isoMeasured ? [{ priority: 'low' as const, text: 'Put smart devices on a guest or IoT network, so a device that is taken over can’t reach your computers.' }] : []),
	];

	const isoKpi: Kpi = isoFailed
		? { key: 'pairs', label: 'Smart devices reaching others', icon: 'iot', value: '—', sub: "Couldn't load" }
		: isoMeasured
			? { key: 'pairs', label: 'Smart devices reaching others', icon: 'iot', value: fmt(iso.pairs.length), sub: `isolation ${iso.segmentation_score}/100, grade ${iso.segmentation_grade ?? '—'}` }
			: { key: 'pairs', label: 'Smart devices reaching others', icon: 'iot', value: 'Not measured', sub: 'No smart (IoT) devices detected yet' };

	return {
		kpis: [scoreKpi(category), unloaded({ key: 'baseline', label: 'Devices with a baseline', icon: 'devices', value: `${fmt(b.scored)} of ${fmt(b.total)}`, sub: 'seen in the last 24 hours' }, sources[0].state === 'failed'), isoKpi],
		drivers: {
			formula: `100 − 10 × ${fmt(b.unscored)} device(s) without a baseline = ${category.score ?? '—'}`,
			counts: [
				`Devices seen in the last 24 hours: ${fmt(b.total)}; with a baseline (a risk score): ${fmt(b.scored)}.`,
				...(isoMeasured ? [`Also checked, not scored: smart-device isolation ${iso.segmentation_score}/100 (grade ${iso.segmentation_grade ?? '—'}). ${iso.recommendation}`.trim()] : []),
			],
			limits: ['This score checks that NetTap has a baseline for each device, not whether your network is split into zones.'],
			bars: [
				{ key: 'scored', label: 'With a baseline', value: b.scored, display: fmt(b.scored), colour: 1 },
				{ key: 'unscored', label: 'Without a baseline', value: b.unscored, display: fmt(b.unscored), colour: 3 },
			],
		},
		sources,
		findings,
		steps,
		notes: [],
	};
}

// --- Alert response ---

/**
 * A rule's page over the snapshot's window. Rules with no name (null or "") have no page, so they
 * open the Alerts list for exactly that row. One helper holds the path, so it can follow the rule page.
 */
export function postureRuleHref(name: string | null, win: { from: string; to: string }): string {
	if (!name) return alertsHrefForSignature(name, { ...win, range: '24h' });
	return `/alerts/rule/${encodeURIComponent(name)}?${windowQuery(win, '24h')}`;
}

/** ET's informational and policy rules: often expected activity, so they get review wording. */
const INFORMATIONAL = /^ET (INFO|POLICY)\b/;

const ALERT_FIX: Record<SeverityLevel, string> = {
	critical: 'Check the devices it involved today.',
	high: 'Check the devices it involved today.',
	medium: 'Check it this week.',
	low: 'Review it; it is often expected activity.',
	info: 'Review it; it is often expected activity.',
};

const STATUS_WORDS: Record<string, string> = { open: 'Open', in_progress: 'In progress', resolved: 'Resolved', closed: 'Closed' };

export function alertReport(data: ReportData): Report {
	const { inputs, category, names, window } = data;
	const counts = inputs.alertCounts.counts;
	const inv = inputs.investigationStats;
	const done = (inv.by_status['resolved'] ?? 0) + (inv.by_status['closed'] ?? 0);
	const open = (inv.by_status['open'] ?? 0) + (inv.by_status['in_progress'] ?? 0);
	const sigs = data.extras.signatures;
	const alertsFailed = inputs.failed.includes('alerts');

	const sources: Source[] = [];
	if (alertsFailed || data.failed.includes('signatures') || !sigs) sources.push(failedSource('rules', 'Busiest rules'));
	else if (counts.total === 0) sources.push(notMeasured('rules', 'Busiest rules', 'No counted rule matches in the last 24 hours', inputs));
	else sources.push({ key: 'rules', label: 'Busiest rules', state: 'measured' });

	const own = inputs.riskScores.scores.filter((s) => (s.alert_count ?? 0) > 0);
	if (inputs.failed.includes('risk') || alertsFailed) sources.push(failedSource('devices', 'Devices whose traffic matched rules'));
	else if (counts.total > 0 && own.length === 0) sources.push({ key: 'devices', label: 'Devices whose traffic matched rules', state: 'unattributed', note: 'The rule matches in the last 24 hours weren’t tied to devices on your network.' });

	const findings: Finding[] = [];
	if (sources[0].state === 'measured' && sigs) {
		sigs.signatures.forEach((s, i) => {
			const level = suricataLevel(s.severity);
			const informational = !!s.signature && INFORMATIONAL.test(s.signature);
			findings.push({
				key: `rule-${i}`,
				severity: level,
				title: s.signature || 'Alerts with no rule name',
				detail: `${fmt(s.count)} alerts in the last 24 hours.${informational ? ' An informational rule: it notes activity rather than an attack.' : ''}`,
				devices: [],
				count: s.count,
				fix: informational ? ALERT_FIX.info : ALERT_FIX[level],
				href: postureRuleHref(s.signature, window),
			});
		});
	}
	if (!inputs.failed.includes('risk')) {
		for (const s of own) {
			const factor = s.factors.find((f) => f.name === 'alert_count');
			findings.push({
				key: `device-${s.ip}`,
				severity: RISK_LEVEL[s.level] ?? 'low',
				title: "Rule matches in this device's own traffic",
				detail: `${fmt(s.alert_count ?? 0)} alerts${factor?.description ? `: ${factor.description}` : ''}.`,
				devices: [device(s.ip, names)],
				count: s.alert_count,
				fix: 'Open the device and check what it was doing at the time.',
			});
		}
	}

	const steps: Step[] = [];
	if (!alertsFailed && counts.total > 0 && inv.total === 0 && !inputs.failed.includes('investigations')) {
		steps.push({ priority: 'high', text: 'Open an investigation for each high-severity group (Investigations › New investigation), note what you found, and close it when done.', href: '/investigations' });
	}
	if (open > 0) steps.push({ priority: 'medium', text: `${fmt(open)} investigation(s) are still open: finish and close them.`, href: '/investigations' });
	if (sigs?.signatures.some((s) => s.signature && INFORMATIONAL.test(s.signature))) {
		steps.push({ priority: 'low', text: 'Review the busiest informational rules. Only once you have confirmed the activity is expected, False positive in the alert’s details hides that rule for every device. Volume alone is never a reason.' });
	}

	const formula =
		counts.total === 0
			? 'No counted alerts in the last 24 hours, so there is nothing to score.'
			: inv.total === 0
				? `${fmt(counts.total)} alerts and no investigations, so the score is 0.`
				: `${fmt(done)} resolved or closed ÷ ${fmt(inv.total)} investigations = ${category.score ?? '—'}%`;

	return {
		kpis: [
			scoreKpi(category),
			unloaded({ key: 'alerts', label: 'Alerts', icon: 'alerts', value: fmt(counts.total), sub: `${fmt(counts.high)} high · ${fmt(counts.medium)} medium · ${fmt(counts.low)} low` }, alertsFailed),
			unloaded({ key: 'investigations', label: 'Investigations (all time)', icon: 'check', value: `${fmt(done)} of ${fmt(inv.total)}`, sub: 'resolved or closed' }, inputs.failed.includes('investigations')),
		],
		drivers: {
			formula,
			counts: ['Counted: investigations marked resolved or closed, out of all investigations.'],
			limits: ['This measures follow-up, not how many alerts there were.', 'Investigations count all time; alerts count the last 24 hours.'],
			bars: Object.entries(inv.by_status).map(([status, n], i) => ({ key: status, label: STATUS_WORDS[status] ?? status, value: n, display: fmt(n), colour: (((i % 6) + 1) as 1 | 2 | 3 | 4 | 5 | 6) })),
		},
		sources,
		findings,
		steps,
		notes: [],
	};
}

// --- Monitoring coverage ---

export const MIRROR_NOTE =
	"In mirror mode NetTap sees only what the switch copies to it; traffic between two devices on one access point, or on a switch port that isn't mirrored, never reaches it.";

export function monitoringReport(data: ReportData): Report {
	const { inputs, category } = data;
	const b = baselineCounts(data);
	const stage = inputs.health.failed ? null : pipelineStage(inputs.health.health?.pipeline);
	const mode = data.failed.includes('mode') ? undefined : data.extras.mode;
	const stats = data.failed.includes('stats') ? undefined : data.extras.stats;
	const loss = stats ? lossWords(stats.loss_window) : null;

	const sources: Source[] = [
		baselineSource(data, 'Devices with a risk score'),
		stage ? { key: 'pipeline', label: 'Data pipeline', state: 'measured' } : failedSource('pipeline', 'Data pipeline'),
		!loss ? failedSource('loss', 'Packet loss') : loss.status === 'unknown' ? { key: 'loss', label: 'Packet loss', state: 'not-measured', note: loss.detail } : { key: 'loss', label: 'Packet loss', state: 'measured' },
		mode ? { key: 'mode', label: 'Capture mode', state: 'measured' } : failedSource('mode', 'Capture mode'),
	];

	const findings: Finding[] = [];
	const steps: Step[] = [];
	if (stage?.status === 'failing') {
		findings.push({ key: 'pipeline', severity: 'high', title: `Data pipeline: ${stage.detail}`, detail: 'While data isn’t arriving, every page reads as quiet.', devices: [], fix: 'Open System to see which part stopped, and restart it from there.', href: '/system' });
		steps.push({ priority: 'high', text: `Fix the data pipeline first: ${stage.detail}.`, href: '/system' });
	}
	if (loss?.status === 'failing') {
		findings.push({ key: 'loss', severity: 'high', title: 'The capture port is losing packets', detail: loss.detail, devices: [], fix: "Check the capture port's link speed, and that the mirror port isn't sent more than it can carry.", href: '/infrastructure' });
		steps.push({ priority: 'high', text: `Stop the packet loss: ${loss.detail}.`, href: '/infrastructure' });
	}
	if (mode?.mode === 'bridge') {
		findings.push({ key: 'mode', severity: 'medium', title: 'Inline bridge mode hides your devices', detail: BRIDGE_NO_DEVICES, devices: [], fix: 'Move NetTap to a mirror (SPAN) port of your main switch’s uplink.' });
		steps.push({ priority: 'medium', text: 'Move NetTap to a mirror port inside your network, so it can tell your devices apart.' });
	} else if (mode?.mode === 'mirror') {
		findings.push({ key: 'mode', severity: 'info', title: 'Mirror mode', detail: MIRROR_NOTE, devices: [], fix: 'Mirror the uplink between your router and your main switch, so the most traffic passes NetTap.' });
		steps.push({ priority: 'low', text: 'Check that the mirror port copies your main uplink.' });
	}
	if (sources[0].state === 'measured' && b.unscored > 0) {
		findings.push(unscoredFinding(b.unscored, 'a risk score'));
		steps.push({ priority: 'medium', text: `${fmt(b.unscored)} device(s) have no risk score yet; check them on the Devices page if they stay that way.`, href: '/devices' });
	}

	return {
		kpis: [
			scoreKpi(category),
			unloaded({ key: 'scored', label: 'Devices with a risk score', icon: 'devices', value: `${fmt(b.scored)} of ${fmt(b.total)}`, sub: 'seen in the last 24 hours' }, sources[0].state === 'failed'),
			{ key: 'pipeline', label: 'Data pipeline', icon: 'system', value: stage ? (stage.status === 'ok' ? 'Running' : stage.status === 'failing' ? 'Failing' : 'Check') : '—', sub: stage?.detail ?? "Couldn't check" },
		],
		drivers: {
			formula: `${fmt(b.scored)} devices with a risk score ÷ ${fmt(b.total)} devices seen = ${category.score ?? '—'}%`,
			counts: [
				`Also checked: data pipeline: ${stage?.detail ?? "couldn't check"}.`,
				`Recent packet loss: ${loss?.detail ?? "couldn't load"}.`,
				`Capture mode: ${mode ? ({ bridge: 'inline bridge', mirror: 'mirror port', dhcp_gateway: 'DHCP gateway' } as Record<string, string>)[mode.mode] ?? mode.mode : "couldn't load"}.`,
			],
			limits: ["The score only counts devices NetTap has seen; a device whose traffic never reaches NetTap is in neither figure."],
			bars: [
				{ key: 'scored', label: 'With a risk score', value: b.scored, display: fmt(b.scored), colour: 1 },
				{ key: 'unscored', label: 'Without a risk score', value: b.unscored, display: fmt(b.unscored), colour: 3 },
			],
		},
		sources,
		findings,
		steps,
		notes: [],
	};
}
