/**
 * NET-349: the one check every Find packets button and the editor's Enter go through. The files a
 * search over [from, to) reads (planFiles, the daemon's own file rule) and whether that is more than
 * the daemon reads in one search (packet_search._check_budget: over max_files or max_bytes).
 */
import type { CapturesResponse } from '$lib/api/packets';
import { planFiles, type FilePlan } from './packets-view';

export interface PlanCheck {
	plan: FilePlan | null;
	overLimit: boolean;
}

export function planCheck(captures: CapturesResponse, from: string, to: string): PlanCheck {
	const plan = planFiles(captures.files, from, to);
	return { plan, overLimit: !!plan && (plan.read.length > captures.limits.max_files || plan.bytes > captures.limits.max_bytes) };
}
