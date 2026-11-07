/**
 * The packet page's ready-made filters (NET-188): the "What" pills, the 37-filter library and
 * the common questions, from the approved mockup.
 *
 * All three live in packet-library.json, plain data ({ groups, kinds, common }), so the device
 * check can have the box's own TShark compile every group and kind filter as it stands. Kind and library filter ids share one
 * namespace: either can go in a question's `kinds` (see filterFor in packet-query.ts).
 */
import data from './packet-library.json';
import type { PacketQuestion } from './packet-query';

export interface LibraryFilter {
	id: string;
	label: string;
	filter: string;
	explain: string;
}
export interface LibraryGroup {
	id: string;
	label: string;
	filters: LibraryFilter[];
}
/** The mockup's 37 filters in six groups, verbatim. */
export const LIBRARY: readonly LibraryGroup[] = data.groups;

/** A "What" pill. "All traffic" has the empty filter: every packet. */
export interface Kind {
	id: string;
	label: string;
	filter: string;
}
export const KINDS: readonly Kind[] = data.kinds;

export interface CommonQuestion {
	id: string;
	label: string;
	/** The mockup's line under the question */
	explain: string;
	/** The device is picked after */
	question: Omit<PacketQuestion, 'limit' | 'device'>;
}

/** The mockup's "Common questions"; each one's filter is the mockup's, word for word (tested). */
// JSON types `when.kind` and `other.kind` as plain strings; packet-library.test.ts checks every question
export const COMMON_QUESTIONS: readonly CommonQuestion[] = data.common as CommonQuestion[];
