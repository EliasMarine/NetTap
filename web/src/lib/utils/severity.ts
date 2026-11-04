/**
 * Severity partition for every severity summary and gauge (PLAN.md §4.1).
 * Built only from severity fields: never from categories (malware-c2 overlaps High).
 */
export type SeverityLevel = 'critical' | 'high' | 'medium' | 'low' | 'info';

export interface SeverityBucket {
	level: SeverityLevel;
	count: number;
}

export interface SeverityInput {
	total: number;
	high: number;
	medium: number;
	low: number;
	/** Only when an API returns a real critical severity field. */
	critical?: number;
}

/** Suricata's alert severity (1 high, 2 medium, 3 low) as a system level; anything else is info. */
export function suricataLevel(severity: number | null | undefined): SeverityLevel {
	return severity === 1 ? 'high' : severity === 2 ? 'medium' : severity === 3 ? 'low' : 'info';
}

/** A smart alert's severity (the daemon's sev_name_map: 1 critical … 4 low, 5 info) as a system level. */
export function smartLevel(severity: number): SeverityLevel {
	if (severity <= 1) return 'critical';
	if (severity === 2) return 'high';
	if (severity === 3) return 'medium';
	return severity === 4 ? 'low' : 'info';
}

const count = (n: number | undefined) => (Number.isFinite(n) && (n as number) > 0 ? Math.floor(n as number) : 0);

/** Mutually exclusive buckets that sum to `total`; info is what the named levels leave. */
export function severityBuckets(input: SeverityInput): SeverityBucket[] {
	const total = count(input.total);
	const named: SeverityBucket[] = [
		...(input.critical === undefined ? [] : [{ level: 'critical' as const, count: count(input.critical) }]),
		{ level: 'high', count: count(input.high) },
		{ level: 'medium', count: count(input.medium) },
		{ level: 'low', count: count(input.low) },
	];
	const namedSum = named.reduce((a, b) => a + b.count, 0);
	return [...named, { level: 'info', count: Math.max(0, total - namedSum) }];
}
