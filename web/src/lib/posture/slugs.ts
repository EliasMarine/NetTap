/**
 * The six Security posture categories (NET-315: moved out of score.ts unchanged). This file imports
 * nothing: src/params.ts uses it, and `vite build` loads src/params.ts with plain Node, which knows
 * no `$lib` aliases (sveltejs/kit#17442).
 */
export const POSTURE_SLUGS = [
	'encryption',
	'dns-security',
	'network-segmentation',
	'patch-currency',
	'alert-response',
	'monitoring-coverage',
] as const;
export type PostureSlug = (typeof POSTURE_SLUGS)[number];
export const isPostureSlug = (value: string): value is PostureSlug => (POSTURE_SLUGS as readonly string[]).includes(value);
