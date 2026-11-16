import type { ParamMatcher } from '@sveltejs/kit';
import { isPostureSlug } from '$lib/posture/score';

/** /compliance/[category=posture]: the six Security posture categories; any other name is a 404. */
export const match: ParamMatcher = (param) => isPostureSlug(param);
