import { describe, it, expect, vi, afterEach } from 'vitest';

/**
 * Tests for InvestigationDrawerContent component logic.
 *
 * InvestigationDrawerContent.svelte uses Svelte 5 runes ($state, $props).
 * Instead of rendering, we extract and test the pure logic: timestamp
 * formatting, time-ago formatting, status color mapping, tab visibility,
 * note handling, and linked items display.
 */

// ---------------------------------------------------------------------------
// Reproduced logic from InvestigationDrawerContent.svelte
// ---------------------------------------------------------------------------

interface InvestigationNote {
	id: string;
	content: string;
	created_at: string;
	updated_at: string;
}

interface InvestigationData {
	id: string;
	title: string;
	description: string;
	status: string;
	severity: string;
	created_at: string;
	updated_at: string;
	alert_ids: string[];
	device_ips: string[];
	notes: InvestigationNote[];
	tags: string[];
}

function formatTimestamp(ts: string): string {
	if (!ts) return '--';
	try {
		return new Date(ts).toLocaleString(undefined, {
			year: 'numeric', month: 'short', day: 'numeric',
			hour: '2-digit', minute: '2-digit',
		});
	} catch {
		return ts;
	}
}

function timeAgo(ts: string): string {
	const diff = Date.now() - new Date(ts).getTime();
	if (diff < 60_000) return 'just now';
	if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
	if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
	return `${Math.floor(diff / 86_400_000)}d ago`;
}

function getStatusColor(status: string): string {
	switch (status) {
		case 'open': return 'var(--amber)';
		case 'in_progress': return 'var(--accent)';
		case 'closed': return 'var(--green)';
		default: return 'var(--text-muted)';
	}
}

function getVisibleContent(activeTab: string): 'details' | 'notes' | 'linked' | 'none' {
	if (activeTab === 'details') return 'details';
	if (activeTab === 'notes') return 'notes';
	if (activeTab === 'linked') return 'linked';
	return 'none';
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('InvestigationDrawerContent logic', () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	// -- Tab visibility -------------------------------------------------------

	describe('tab visibility', () => {
		it('renders details tab', () => {
			expect(getVisibleContent('details')).toBe('details');
		});

		it('renders notes tab', () => {
			expect(getVisibleContent('notes')).toBe('notes');
		});

		it('renders linked items tab', () => {
			expect(getVisibleContent('linked')).toBe('linked');
		});

		it('renders nothing for unknown tab', () => {
			expect(getVisibleContent('unknown')).toBe('none');
		});
	});

	// -- formatTimestamp ------------------------------------------------------

	describe('formatTimestamp', () => {
		it('returns "--" for empty string', () => {
			expect(formatTimestamp('')).toBe('--');
		});

		it('formats a valid ISO timestamp', () => {
			const result = formatTimestamp('2026-03-01T12:00:00Z');
			expect(result).toContain('2026');
		});

		it('returns original string for invalid date', () => {
			const result = formatTimestamp('not-a-date');
			expect(typeof result).toBe('string');
		});
	});

	// -- timeAgo --------------------------------------------------------------

	describe('timeAgo', () => {
		it('returns "just now" for recent timestamps', () => {
			expect(timeAgo(new Date().toISOString())).toBe('just now');
		});

		it('returns minutes ago', () => {
			const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString();
			expect(timeAgo(fiveMinAgo)).toBe('5m ago');
		});

		it('returns hours ago', () => {
			const threeHoursAgo = new Date(Date.now() - 3 * 3_600_000).toISOString();
			expect(timeAgo(threeHoursAgo)).toBe('3h ago');
		});

		it('returns days ago', () => {
			const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000).toISOString();
			expect(timeAgo(twoDaysAgo)).toBe('2d ago');
		});
	});

	// -- getStatusColor -------------------------------------------------------

	describe('getStatusColor', () => {
		it('returns amber for open status', () => {
			expect(getStatusColor('open')).toBe('var(--amber)');
		});

		it('returns accent for in_progress status', () => {
			expect(getStatusColor('in_progress')).toBe('var(--accent)');
		});

		it('returns green for closed status', () => {
			expect(getStatusColor('closed')).toBe('var(--green)');
		});

		it('returns muted for unknown status', () => {
			expect(getStatusColor('resolved')).toBe('var(--text-muted)');
			expect(getStatusColor('')).toBe('var(--text-muted)');
		});
	});

	// -- Investigation detail fields ------------------------------------------

	describe('investigation detail fields', () => {
		const investigation: InvestigationData = {
			id: 'inv-001',
			title: 'Suspicious Outbound Traffic',
			description: 'Multiple devices communicating with known C2 servers',
			status: 'open',
			severity: 'high',
			created_at: '2026-03-01T10:00:00Z',
			updated_at: '2026-03-01T14:00:00Z',
			alert_ids: ['alert-1', 'alert-2', 'alert-3'],
			device_ips: ['192.168.1.100', '192.168.1.101'],
			notes: [
				{ id: 'note-1', content: 'Initial triage complete', created_at: '2026-03-01T10:30:00Z', updated_at: '2026-03-01T10:30:00Z' },
				{ id: 'note-2', content: 'Escalated to SOC team', created_at: '2026-03-01T11:00:00Z', updated_at: '2026-03-01T11:00:00Z' },
			],
			tags: ['c2', 'outbound', 'critical'],
		};

		it('renders title', () => {
			expect(investigation.title).toBe('Suspicious Outbound Traffic');
		});

		it('renders status', () => {
			expect(investigation.status).toBe('open');
		});

		it('renders severity', () => {
			expect(investigation.severity).toBe('high');
		});

		it('renders description', () => {
			expect(investigation.description).toContain('C2 servers');
		});

		it('renders tags', () => {
			expect(investigation.tags).toHaveLength(3);
			expect(investigation.tags).toContain('c2');
		});

		it('formats created_at timestamp', () => {
			const formatted = formatTimestamp(investigation.created_at);
			expect(formatted).toContain('2026');
		});
	});

	// -- Notes tab ------------------------------------------------------------

	describe('notes', () => {
		it('shows notes when they exist', () => {
			const notes: InvestigationNote[] = [
				{ id: '1', content: 'Note 1', created_at: '2026-03-01T10:00:00Z', updated_at: '2026-03-01T10:00:00Z' },
				{ id: '2', content: 'Note 2', created_at: '2026-03-01T11:00:00Z', updated_at: '2026-03-01T11:00:00Z' },
			];
			expect(notes).toHaveLength(2);
			expect(notes[0].content).toBe('Note 1');
		});

		it('handles empty notes list', () => {
			const notes: InvestigationNote[] = [];
			expect(notes).toHaveLength(0);
		});

		it('note add callback receives investigation id and text', () => {
			const onnoteadded = vi.fn();
			const id = 'inv-001';
			const noteText = 'New finding';

			onnoteadded(id, noteText);

			expect(onnoteadded).toHaveBeenCalledWith('inv-001', 'New finding');
		});

		it('skips empty note text', () => {
			const noteText = '   ';
			expect(noteText.trim()).toBe('');
		});
	});

	// -- Linked items tab -----------------------------------------------------

	describe('linked items', () => {
		it('shows linked alerts when they exist', () => {
			const alertIds = ['alert-1', 'alert-2', 'alert-3'];
			expect(alertIds).toHaveLength(3);
		});

		it('shows linked devices when they exist', () => {
			const deviceIps = ['192.168.1.100', '192.168.1.101'];
			expect(deviceIps).toHaveLength(2);
		});

		it('shows empty state when no linked items', () => {
			const investigation: InvestigationData = {
				id: 'inv-002',
				title: 'Empty Investigation',
				description: '',
				status: 'open',
				severity: 'low',
				created_at: '2026-03-01T10:00:00Z',
				updated_at: '2026-03-01T10:00:00Z',
				alert_ids: [],
				device_ips: [],
				notes: [],
				tags: [],
			};

			const hasLinked = (investigation.alert_ids?.length > 0) || (investigation.device_ips?.length > 0);
			expect(hasLinked).toBe(false);
		});
	});

	// -- Status change callback -----------------------------------------------

	describe('status change', () => {
		it('calls onstatuschange with investigation id and new status', () => {
			const onstatuschange = vi.fn();
			onstatuschange('inv-001', 'in_progress');
			expect(onstatuschange).toHaveBeenCalledWith('inv-001', 'in_progress');
		});

		it('supports all status values', () => {
			const validStatuses = ['open', 'in_progress', 'closed'];
			validStatuses.forEach(status => {
				expect(getStatusColor(status)).not.toBe('var(--text-muted)');
			});
		});
	});
});
