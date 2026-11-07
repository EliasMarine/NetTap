<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { registerPageRefresh, outcome, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { fetchCaptureStatus, toggleCapture, updateCaptureSettings } from '$lib/api/capture';
	import { previewCleanup, executeCleanup, type CleanupPreview } from '$lib/api/storage';
	import { getUnifiStatus } from '$lib/api/unifi';
	import { loadFailed } from '$lib/utils/load-failed';
	import { formatDuration } from '$lib/utils/tshark-helpers';
	import { formatBytes } from '$lib/api/logs';
	import ThemePicker from '$lib/components/ThemePicker.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Pills, { type PillOption } from '$lib/components/ui/Pills.svelte';
	import StatStrip from '$lib/components/ui/StatStrip.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import { formatTime } from '$lib/utils/time';
	import { DISPLAY_SETTINGS_KEY, DRILL_RANGES, savedDefaultRange, type DrillRangeValue } from '$lib/utils/drilldown';

	type TabId = 'notifications' | 'retention' | 'capture' | 'api-keys' | 'network' | 'integrations' | 'display' | 'about';

	let activeTab = $state<TabId>('notifications');

	// Values are id-safe: Pills builds settings-tab-{value} / settings-panel-{value} from them
	const TABS: PillOption<TabId>[] = [
		{ value: 'notifications', label: 'Notifications' },
		{ value: 'retention', label: 'Retention' },
		{ value: 'capture', label: 'Capture' },
		{ value: 'api-keys', label: 'API keys' },
		{ value: 'network', label: 'Network' },
		{ value: 'integrations', label: 'Integrations' },
		{ value: 'display', label: 'Display' },
		{ value: 'about', label: 'About' },
	];

	// --- Notifications state ---
	let severityThreshold = $state<string>('medium');
	let emailEnabled = $state(false);
	let emailAddress = $state('');
	let webhookUrl = $state('');
	let notifSaving = $state(false);
	let notifMessage = $state('');
	let notifError = $state(false);
	// a failed load leaves blank fields; saving them would wipe the real config
	let notifLoadFailed = $state(false);
	let testingSending = $state(false);
	let testMessage = $state('');
	let testError = $state(false);

	// --- Retention state ---
	let retentionConfig = $state({
		hot_days: 90,
		warm_days: 180,
		cold_days: 30,
		disk_threshold: 80,
		emergency_threshold: 90,
	});
	let diskUsage = $state<number | null>(null);
	let lastPruneAt = $state<string | null>(null);
	let storageStatusFailed = $state(false);
	let storageLoading = $state(true);
	let ilmStatus = $state<{ synced: boolean; last_applied: string | null; pending_retry: boolean; policies: Record<string, string> } | null>(null);
	let retentionSaving = $state(false);
	let retentionMessage = $state('');
	let retentionError = $state(false);
	// Save stays off until the real values load, so defaults can't overwrite them
	let retentionLoad = $state<'loading' | 'ok' | 'failed'>('loading');

	// --- Manual Cleanup state ---
	let cleanupDays = $state(60);
	let cleanupPreview = $state<CleanupPreview | null>(null);
	// Days the shown preview was computed for — the delete must use these, not the live input
	let cleanupPreviewDays = $state<number | null>(null);
	let cleanupPreviewing = $state(false);
	let cleanupExecuting = $state(false);
	let showCleanupConfirm = $state(false);
	let cleanupMessage = $state('');
	let cleanupError = $state(false);

	// --- Network state (excluded IPs) ---
	let excludedIps = $state<string[]>([]);
	let newExcludedIp = $state('');
	let networkSaving = $state(false);
	let networkMessage = $state('');
	let networkError = $state(false);
	let networkLoading = $state(true);
	let networkLoadFailed = $state(false);

	// --- API Keys state ---
	let apiKeysStatus = $state<Record<string, boolean>>({});
	let apiKeysLoading = $state(true);
	let apiKeysSaving = $state(false);
	let apiKeysMessage = $state('');
	let apiKeysError = $state(false);
	// Track modified fields only — don't send unchanged values
	let apiKeyValues = $state<Record<string, string>>({});

	// --- Capture state ---
	let captureEnabled = $state(true);
	let captureMaxFileSize = $state(100);
	let captureRotateMinutes = $state<number | null>(null);
	let captureContainerRunning = $state(false);
	let captureContainerStatus = $state('unknown');
	let captureLoading = $state(true);
	let captureLoadFailed = $state(false);
	let captureToggling = $state(false);
	let captureSaving = $state(false);
	let captureMessage = $state('');
	let captureError = $state(false);

	// --- Display state ---
	// OLD CODE START — NET-195: no page read these; each page owns its Auto toggle, and times are browser-local
	// let autoRefresh = $state('30');
	// let timezone = $state('local');
	// let defaultTimeRange = $state('1h');
	// OLD CODE END
	/** The range pages open on (NET-195); '' is each page's own. */
	let defaultRange = $state<DrillRangeValue | ''>('');
	let displaySaving = $state(false);
	let displayMessage = $state('');
	let displayError = $state(false);

	// --- UniFi Integration state ---
	let unifiControllerUrl = $state('');
	let unifiApiKey = $state('');
	let unifiSiteId = $state('');
	let unifiSites = $state<{ id: string; name?: string; desc?: string }[]>([]);
	let unifiConfigured = $state(false);
	let unifiConnected = $state(false);
	let unifiCacheCounts = $state<{ clients: number; devices: number } | null>(null);
	let unifiLastPoll = $state<string | null>(null);
	let unifiLoading = $state(true);
	// #96: a failed status read used to show the form as "not configured"
	let unifiStatusFailed = $state(false);
	let unifiSaving = $state(false);
	let unifiTesting = $state(false);
	let unifiMessage = $state('');
	let unifiError = $state(false);
	let unifiSitesLoading = $state(false);

	// --- About state ---
	let version = $state('…');
	let uptime = $state('…');
	// OLD CODE: let buildInfo = $state('…'); (S11: the daemon sends no build, so it fell back to "Development build")
	/** The build the daemon reports; null hides the row rather than claim one. */
	let buildInfo = $state<string | null>(null);

	async function loadNotificationConfig() {
		try {
			const res = await fetch('/api/notifications/config');
			if (res.ok) {
				const data = await res.json();
				severityThreshold = data.severityThreshold ?? 'medium';
				emailEnabled = data.email?.enabled ?? false;
				emailAddress = data.email?.recipients?.[0] ?? '';
				webhookUrl = data.webhook?.url ?? '';
				notifLoadFailed = false;
				return;
			}
		} catch {
			// Falls through to failed
		}
		notifLoadFailed = true;
	}

	async function loadRetention() {
		try {
			const res = await fetch('/api/setup/storage');
			if (res.ok) {
				const data = await res.json();
				// source 'mock' = the daemon didn't answer and these are built-in defaults
				if (data.source !== 'mock') {
					// GET /api/setup/storage returns a FLAT StorageStatus object
					// (hot_days, warm_days, etc. are top-level, not nested under retention)
					retentionConfig.hot_days = data.hot_days ?? 90;
					retentionConfig.warm_days = data.warm_days ?? 180;
					retentionConfig.cold_days = data.cold_days ?? 30;
					retentionConfig.disk_threshold = data.disk_threshold_percent ?? 80;
					retentionConfig.emergency_threshold = data.emergency_threshold_percent ?? 90;
					retentionLoad = 'ok';
					return;
				}
			}
		} catch {
			// Falls through to 'failed'
		}
		retentionLoad = 'failed';
	}

	async function loadDiskUsage() {
		try {
			const res = await fetch('/api/storage/status');
			if (res.ok) {
				const data = await res.json();
				diskUsage = data.disk_usage_percent ?? data.usage_percent ?? null;
				lastPruneAt = data.last_prune_at ?? null;
				ilmStatus = data.ilm_status ?? null;
				storageStatusFailed = false;
				storageLoading = false;
				return;
			}
		} catch {
			// OLD CODE START — a failure left "Loading...", "Never (daemon starting...)" and a Problem badge
			// // Will stay null
			// OLD CODE END
		}
		storageStatusFailed = true;
		storageLoading = false;
	}

	// --- Retention health helpers ---
	function timeAgo(isoString: string): string {
		const diff = Date.now() - new Date(isoString).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	let retentionHealth = $derived.by(() => {
		const ilmOk = ilmStatus?.synced ?? false;
		const ilmPending = ilmStatus?.pending_retry ?? false;
		const pruneOk = lastPruneAt ? (Date.now() - new Date(lastPruneAt).getTime()) < 600000 : false;
		const pruneStale = lastPruneAt ? (Date.now() - new Date(lastPruneAt).getTime()) > 1800000 : true;
		const diskPct = diskUsage ?? 0;
		const diskHigh = diskPct >= (retentionConfig.disk_threshold ?? 80);
		const diskCritical = diskPct >= (retentionConfig.emergency_threshold ?? 90);

		// OLD CODE START — a failed status read scored as a Problem
		// let status: 'healthy' | 'attention' | 'problem' = 'healthy';
		// OLD CODE END
		let status: 'healthy' | 'attention' | 'problem' | 'unknown' = 'healthy';
		if (storageStatusFailed) status = 'unknown';
		else if ((!ilmOk && !ilmPending) || diskCritical) status = 'problem';
		else if (ilmPending || diskHigh || !pruneOk) status = 'attention';

		return { status, ilmOk, ilmPending, pruneOk, pruneStale, diskPct, diskHigh, diskCritical };
	});

	/** True when both reads answered (the page loader's outcome). */
	async function loadAbout(): Promise<boolean> {
		try {
			const [healthRes, versionsRes] = await Promise.all([
				fetch('/api/system/health'),
				fetch('/api/system/versions'),
			]);
			// OLD CODE START — 2026-11-02: showed raw seconds ("21970.08") and a
			// hardcoded '0.3.0' (the API returns { versions: [...] }, no top-level version)
			// if (healthRes.ok) {
			// 	const data = await healthRes.json();
			// 	uptime = data.uptime ?? 'Unknown';
			// }
			// if (versionsRes.ok) {
			// 	const data = await versionsRes.json();
			// 	version = data.nettap ?? data.version ?? '0.3.0';
			// 	buildInfo = data.build ?? data.commit ?? 'Development build';
			// }
			// OLD CODE END
			if (healthRes.ok) {
				const data = await healthRes.json();
				uptime = typeof data.uptime === 'number' ? formatDuration(data.uptime) : 'Unknown';
			}
			if (versionsRes.ok) {
				const data = await versionsRes.json();
				const daemon = (data.versions ?? []).find(
					(v: { name?: string }) => v.name === 'nettap-daemon'
				);
				version = daemon?.current_version ?? 'Unknown';
				// OLD CODE: buildInfo = data.build ?? data.commit ?? 'Development build';
				buildInfo = data.build ?? data.commit ?? null;
			}
			return healthRes.ok && versionsRes.ok;
		} catch {
			// Will use defaults
			return false;
		}
	}

	// OLD CODE START — NET-195: auto-refresh and timezone are gone, and the range is read as the pages read it
	// async function loadDisplaySettings() {
	// 	try {
	// 		const stored = localStorage.getItem('nettap-display-settings');
	// 		if (stored) {
	// 			const parsed = JSON.parse(stored);
	// 			autoRefresh = parsed.autoRefresh ?? '30';
	// 			timezone = parsed.timezone ?? 'local';
	// 			// OLD CODE: defaultTimeRange = parsed.defaultTimeRange ?? '1h'; (NET-192 PR 4: a saved 15m or 4h is no longer offered)
	// 			defaultTimeRange = ['1h', '6h', '24h', '7d', '30d'].includes(parsed.defaultTimeRange) ? parsed.defaultTimeRange : '1h';
	// 		}
	// 	} catch {
	// 		// Will use defaults
	// 	}
	// }
	// OLD CODE END
	function loadDisplaySettings() {
		defaultRange = savedDefaultRange() ?? '';
	}

	async function loadExcludedIps() {
		networkLoading = true;
		try {
			const res = await fetch('/api/settings/excluded-ips');
			if (res.ok) {
				const data = await res.json();
				excludedIps = data.excluded_ips ?? [];
				networkLoadFailed = false;
				return;
			}
			networkLoadFailed = true;
		} catch {
			networkLoadFailed = true;
		} finally {
			networkLoading = false;
		}
	}

	async function loadApiKeys() {
		apiKeysLoading = true;
		try {
			const res = await fetch('/api/settings/api-keys');
			if (res.ok) {
				const data = await res.json();
				apiKeysStatus = data.keys ?? {};
			}
		} catch {
			// Will use empty default
		} finally {
			apiKeysLoading = false;
		}
	}

	async function saveApiKeys() {
		apiKeysSaving = true;
		apiKeysMessage = '';
		apiKeysError = false;

		// Only send fields that have been modified (non-empty)
		const payload: Record<string, string> = {};
		for (const [key, value] of Object.entries(apiKeyValues)) {
			if (value.trim()) {
				payload[key] = value.trim();
			}
		}

		if (Object.keys(payload).length === 0) {
			apiKeysMessage = 'No changes to save. Enter a value in at least one field.';
			apiKeysError = true;
			apiKeysSaving = false;
			return;
		}

		try {
			const res = await fetch('/api/settings/api-keys', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
			});
			const data = await res.json();
			if (res.ok) {
				apiKeysMessage = `Saved ${data.saved_count ?? Object.keys(payload).length} key(s) successfully.`;
				apiKeysStatus = data.keys ?? apiKeysStatus;
				// Clear input fields after successful save
				apiKeyValues = {};
			} else {
				apiKeysMessage = data.error || 'Failed to save API keys.';
				apiKeysError = true;
			}
		} catch {
			apiKeysMessage = 'Failed to connect to server.';
			apiKeysError = true;
		} finally {
			apiKeysSaving = false;
		}
	}

	async function saveExcludedIps() {
		networkSaving = true;
		networkMessage = '';
		networkError = false;
		try {
			const res = await fetch('/api/settings/excluded-ips', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ excluded_ips: excludedIps }),
			});
			if (res.ok) {
				networkMessage = 'Excluded IPs saved. Changes take effect immediately.';
			} else {
				const data = await res.json();
				networkMessage = data.error || 'Failed to save excluded IPs.';
				networkError = true;
			}
		} catch {
			networkMessage = 'Failed to connect to server.';
			networkError = true;
		} finally {
			networkSaving = false;
		}
	}

	function addExcludedIp() {
		const ip = newExcludedIp.trim();
		if (!ip) return;
		// Basic IP format validation
		if (!/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(ip)) {
			networkMessage = 'Please enter a valid IPv4 address.';
			networkError = true;
			return;
		}
		if (excludedIps.includes(ip)) {
			networkMessage = `${ip} is already in the exclusion list.`;
			networkError = true;
			return;
		}
		excludedIps = [...excludedIps, ip];
		newExcludedIp = '';
		networkMessage = '';
	}

	function removeExcludedIp(ip: string) {
		excludedIps = excludedIps.filter((i) => i !== ip);
	}

	// --- Capture functions ---
	async function loadCaptureSettings() {
		captureLoading = true;
		try {
			const status = await fetchCaptureStatus();
			captureLoadFailed = false;
			captureEnabled = status.enabled;
			captureMaxFileSize = status.maxFileSizeMB;
			captureRotateMinutes = status.rotateMinutes ?? null;
			captureContainerRunning = status.containerRunning;
			captureContainerStatus = status.containerStatus;
		} catch {
			captureLoadFailed = true;
		} finally {
			captureLoading = false;
		}
	}

	async function handleCaptureToggle() {
		captureToggling = true;
		captureMessage = '';
		captureError = false;
		try {
			const result = await toggleCapture(!captureEnabled);
			captureEnabled = result.enabled;
			captureContainerRunning = result.containerRunning;
			captureContainerStatus = result.containerStatus;
			captureMessage = captureEnabled ? 'PCAP capture enabled' : 'PCAP capture disabled';
		} catch (err) {
			captureError = true;
			captureMessage = err instanceof Error ? err.message : 'Toggle failed';
		} finally {
			captureToggling = false;
		}
	}

	async function saveCaptureSettings() {
		captureSaving = true;
		captureMessage = '';
		captureError = false;
		try {
			const result = await updateCaptureSettings({ maxFileSizeMB: captureMaxFileSize });
			captureMaxFileSize = result.maxFileSizeMB;
			// OLD CODE START — 2026-11-06 (NET-166): netsniff-ng counts this setting in MiB, not MB
			// captureMessage = result.restarted
			// 	? `File size updated to ${result.maxFileSizeMB} MB. Container restarted.`
			// 	: `File size updated to ${result.maxFileSizeMB} MB.`;
			// OLD CODE END
			captureMessage = result.restarted
				? `File size updated to ${result.maxFileSizeMB} MiB. Container restarted.`
				: `File size updated to ${result.maxFileSizeMB} MiB.`;
		} catch (err) {
			captureError = true;
			captureMessage = err instanceof Error ? err.message : 'Save failed';
		} finally {
			captureSaving = false;
		}
	}

	// --- UniFi functions ---
	// OLD CODE START — read `last_poll`, which the daemon never sends (it sends
	// `last_poll_time` in epoch seconds), so "Last Poll" never showed
	// async function loadUnifiStatus() {
	// 	unifiLoading = true;
	// 	try {
	// 		const res = await fetch('/api/integrations/unifi/status');
	// 		if (res.ok) {
	// 			const data = await res.json();
	// 			unifiConfigured = data.configured ?? false;
	// 			unifiControllerUrl = data.controller_url ?? '';
	// 			unifiConnected = data.connected ?? false;
	// 			unifiCacheCounts = data.cache_counts ?? null;
	// 			unifiLastPoll = data.last_poll ?? null;
	// 			if (data.site_id) unifiSiteId = data.site_id;
	// 		}
	// 	} catch {
	// 		// Will use defaults
	// 	} finally {
	// 		unifiLoading = false;
	// 	}
	// }
	// OLD CODE END
	function unifiPollIso(epochSeconds: unknown): string | null {
		return typeof epochSeconds === 'number' && epochSeconds > 0
			? new Date(epochSeconds * 1000).toISOString()
			: null;
	}

	async function loadUnifiStatus() {
		unifiLoading = true;
		try {
			const status = await getUnifiStatus();
			unifiConfigured = status.configured;
			unifiControllerUrl = status.controller_url ?? '';
			unifiConnected = status.connected;
			unifiCacheCounts = status.configured
				? { clients: status.cache_counts.clients ?? 0, devices: status.cache_counts.devices ?? 0 }
				: null;
			unifiLastPoll = unifiPollIso(status.last_poll_time);
			if (status.site_id) unifiSiteId = status.site_id;
			unifiStatusFailed = false;
		} catch {
			unifiStatusFailed = true;
		} finally {
			unifiLoading = false;
		}
	}

	async function loadUnifiSites() {
		unifiSitesLoading = true;
		try {
			const res = await fetch('/api/integrations/unifi/sites');
			if (res.ok) {
				const data = await res.json();
				unifiSites = data.sites ?? [];
			}
		} catch {
			// Sites will remain empty
		} finally {
			unifiSitesLoading = false;
		}
	}

	async function saveUnifiConfig() {
		unifiSaving = true;
		unifiMessage = '';
		unifiError = false;

		if (!unifiControllerUrl.trim()) {
			unifiMessage = 'Controller URL is required.';
			unifiError = true;
			unifiSaving = false;
			return;
		}
		if (!unifiApiKey.trim() && !unifiConfigured) {
			unifiMessage = 'API Key is required.';
			unifiError = true;
			unifiSaving = false;
			return;
		}

		try {
			const payload: Record<string, string> = {
				controller_url: unifiControllerUrl.trim(),
			};
			// Only send api_key if user entered one (leave blank to keep existing)
			if (unifiApiKey.trim()) {
				payload.api_key = unifiApiKey.trim();
			}
			// OLD CODE START — a whitespace-only site id was posted as-is
			// if (unifiSiteId) {
			// 	payload.site_id = unifiSiteId;
			// }
			// OLD CODE END
			// Omit site_id when blank so the daemon keeps the saved site
			const siteId = unifiSiteId.trim();
			if (siteId) {
				payload.site_id = siteId;
			}

			const res = await fetch('/api/integrations/unifi/configure', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
			});
			const data = await res.json();
			if (res.ok) {
				unifiMessage = 'UniFi configuration saved successfully.';
				unifiConfigured = true;
				unifiApiKey = ''; // Clear after save
				// Now test the connection
				await testUnifiConnection();
			} else {
				unifiMessage = data.error || 'Failed to save UniFi configuration.';
				unifiError = true;
			}
		} catch {
			unifiMessage = 'Failed to connect to server.';
			unifiError = true;
		} finally {
			unifiSaving = false;
		}
	}

	async function testUnifiConnection() {
		unifiTesting = true;
		unifiMessage = '';
		unifiError = false;

		try {
			const res = await fetch('/api/integrations/unifi/test', { method: 'POST' });
			const data = await res.json();
			if (res.ok && data.success) {
				unifiConnected = true;
				unifiMessage = 'Connection successful.';
				if (data.status?.cache_counts) {
					unifiCacheCounts = data.status.cache_counts;
				}
				// OLD CODE START — `last_poll` is not a daemon field
				// if (data.status?.last_poll) {
				// 	unifiLastPoll = data.status.last_poll;
				// }
				// OLD CODE END
				unifiLastPoll = unifiPollIso(data.status?.last_poll_time) ?? unifiLastPoll;
				// Fetch available sites
				await loadUnifiSites();
			} else {
				unifiConnected = false;
				unifiMessage = data.error || data.message || 'Connection test failed.';
				unifiError = true;
			}
		} catch {
			unifiConnected = false;
			unifiMessage = 'Failed to connect to server.';
			unifiError = true;
		} finally {
			unifiTesting = false;
		}
	}

	function formatUnifiPollTime(isoString: string): string {
		const diff = Date.now() - new Date(isoString).getTime();
		const secs = Math.floor(diff / 1000);
		if (secs < 60) return `${secs}s ago`;
		const mins = Math.floor(secs / 60);
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.floor(hours / 24)}d ago`;
	}

	// OLD CODE START — NET-192 PR 4: the top bar's Refresh did nothing here; the reads go through the page loader
	// onMount(() => {
	// 	loadNotificationConfig();
	// 	loadRetention();
	// 	loadDiskUsage();
	// 	loadExcludedIps();
	// 	loadApiKeys();
	// 	loadAbout();
	// 	loadDisplaySettings();
	// 	loadCaptureSettings();
	// 	loadUnifiStatus();
	// });
	// OLD CODE END
	/**
	 * The top bar's Refresh: the read-only status sections only (Retention health, About), never a
	 * form, so an unsaved edit survives it. Capture and UniFi status share their loaders with their
	 * forms, so they stay read once, with the forms.
	 */
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// shortcut: each read writes its own section unguarded; neither takes a range or filter, so an
		// older reply answers the same question. Copy the query into locals if a section gains one.
		const [, aboutOk] = await Promise.all([loadDiskUsage(), loadAbout()]);
		if (!guard.current(g)) return 'skipped';
		return outcome([storageStatusFailed, !aboutOk].map((bad): PromiseSettledResult<null> => (bad ? { status: 'rejected', reason: null } : { status: 'fulfilled', value: null })));
	}

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);
	// The forms load once here, and again after a save, as before
	onMount(() => {
		loadNotificationConfig();
		loadRetention();
		loadExcludedIps();
		loadApiKeys();
		loadDisplaySettings();
		loadCaptureSettings();
		loadUnifiStatus();
		void refresh.run();
	});

	async function saveNotifications() {
		notifSaving = true;
		notifMessage = '';
		notifError = false;
		try {
			const res = await fetch('/api/notifications/config', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					severityThreshold,
					email: {
						enabled: emailEnabled,
						recipients: emailAddress ? [emailAddress] : [],
					},
					webhook: {
						url: webhookUrl || null,
					},
				}),
			});
			if (res.ok) {
				notifMessage = 'Notification settings saved successfully.';
			} else {
				const data = await res.json();
				notifMessage = data.error || 'Failed to save notification settings.';
				notifError = true;
			}
		} catch {
			notifMessage = 'Failed to connect to server.';
			notifError = true;
		} finally {
			notifSaving = false;
		}
	}

	async function sendTestNotification() {
		testingSending = true;
		testMessage = '';
		testError = false;
		try {
			const res = await fetch('/api/notifications/test', { method: 'POST' });
			const data = await res.json();
			if (res.ok) {
				testMessage = 'Test notification sent successfully.';
			} else {
				testMessage = data.error || 'Failed to send test notification.';
				testError = true;
			}
		} catch {
			testMessage = 'Failed to connect to server.';
			testError = true;
		} finally {
			testingSending = false;
		}
	}

	async function saveRetention() {
		retentionSaving = true;
		retentionMessage = '';
		retentionError = false;
		try {
			const res = await fetch('/api/setup/storage', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					hot_days: retentionConfig.hot_days,
					warm_days: retentionConfig.warm_days,
					cold_days: retentionConfig.cold_days,
					disk_threshold_percent: retentionConfig.disk_threshold,
					emergency_threshold_percent: retentionConfig.emergency_threshold,
				}),
			});
			if (res.ok) {
				const result = await res.json();
				if (result.ilm_applied) {
					retentionMessage = 'Retention settings saved and applied to OpenSearch.';
				} else {
					retentionMessage = 'Retention settings saved. OpenSearch policies will sync shortly.';
				}
			} else {
				// OLD CODE START — didn't separate "not saved" from "may have been saved"
				// const data = await res.json();
				// retentionMessage = data.error || 'Failed to save configuration.';
				// OLD CODE END
				const data = await res.json().catch(() => ({}));
				retentionMessage = data.outcome_unknown
					? `Outcome unknown — check again. ${data.error ?? ''} Reload this page to see whether the settings were saved.`
					: `Not saved: ${data.error || `HTTP ${res.status}`}`;
				retentionError = true;
			}
		} catch {
			// OLD CODE START
			// retentionMessage = 'Failed to connect to server.';
			// OLD CODE END
			retentionMessage = 'Not saved: could not reach the NetTap server.';
			retentionError = true;
		} finally {
			retentionSaving = false;
		}
	}

	// OLD CODE START — 2026-11-06 (NET-166): a copy of formatBytes in $lib/api/logs, 1024-based under decimal labels; the shared one is decimal
	// function formatCleanupBytes(bytes: number): string {
	// 	if (bytes === 0) return '0 B';
	// 	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	// 	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	// 	return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
	// }
	// OLD CODE END

	async function handleCleanupPreview() {
		if (cleanupDays < 1) return;
		cleanupPreviewing = true;
		cleanupMessage = '';
		cleanupError = false;
		cleanupPreview = null;
		cleanupPreviewDays = null;
		showCleanupConfirm = false;

		const days = cleanupDays;
		try {
			// OLD CODE START — preview and execute both read the live input, so editing
			// the days after previewing deleted a different range than the one shown
			// cleanupPreview = await previewCleanup(cleanupDays);
			// OLD CODE END
			cleanupPreview = await previewCleanup(days);
			cleanupPreviewDays = days;
		} catch (err: unknown) {
			cleanupMessage = err instanceof Error ? err.message : 'Failed to preview cleanup';
			cleanupError = true;
		} finally {
			cleanupPreviewing = false;
		}
	}

	async function handleCleanupExecute() {
		if (cleanupPreviewDays === null) return;
		cleanupExecuting = true;
		cleanupMessage = '';
		cleanupError = false;

		try {
			// OLD CODE START — used the live input instead of the previewed days
			// const result = await executeCleanup(cleanupDays);
			// OLD CODE END
			const result = await executeCleanup(cleanupPreviewDays);
			const freedStr = formatBytes(result.freed_bytes_estimate);
			cleanupMessage = `Cleanup complete: deleted ${result.deleted_indices} indices and ${result.deleted_pcap_files} PCAP files, freed ${freedStr}.`;
			if (result.errors.length > 0) {
				cleanupMessage += ` (${result.errors.length} errors)`;
			}
			cleanupError = false;
			cleanupPreview = null;
			cleanupPreviewDays = null;
			showCleanupConfirm = false;

			// Refresh disk usage
			try {
				const res = await fetch('/api/storage/status');
				if (res.ok) {
					const data = await res.json();
					diskUsage = data.disk_usage_percent ?? diskUsage;
				}
			} catch {
				// Non-critical, disk usage will update on next load
			}
		} catch (err: unknown) {
			cleanupMessage = err instanceof Error ? err.message : 'Cleanup failed';
			cleanupError = true;
		} finally {
			cleanupExecuting = false;
		}
	}

	function cancelCleanup() {
		showCleanupConfirm = false;
		cleanupPreview = null;
		cleanupPreviewDays = null;
		cleanupMessage = '';
	}

	function saveDisplay() {
		displaySaving = true;
		displayMessage = '';
		displayError = false;
		try {
			// OLD CODE START — NET-195: the new field only; "Each page's own" saves nothing
			// localStorage.setItem(
			// 	'nettap-display-settings',
			// 	JSON.stringify({ autoRefresh, timezone, defaultTimeRange })
			// );
			// OLD CODE END
			if (defaultRange) localStorage.setItem(DISPLAY_SETTINGS_KEY, JSON.stringify({ defaultRange }));
			else localStorage.removeItem(DISPLAY_SETTINGS_KEY);
			displayMessage = 'Display settings saved.';
		} catch {
			displayMessage = 'Failed to save display settings.';
			displayError = true;
		} finally {
			displaySaving = false;
		}
	}

	const severityOptions: { value: string; label: string }[] = [
		{ value: 'critical', label: 'Critical only' },
		{ value: 'high', label: 'High and above' },
		{ value: 'medium', label: 'Medium and above' },
		{ value: 'low', label: 'All severities' },
	];
</script>

<svelte:head>
	<title>Settings | NetTap</title>
</svelte:head>

{#snippet feedback(message: string, isError: boolean)}
	{#if message}
		<div class={['notice', isError ? 'is-error' : 'is-ok']} role={isError ? 'alert' : 'status'}>
			<Icon name={isError ? 'warn' : 'check'} />{message}
		</div>
	{/if}
{/snippet}

{#snippet configured(set: boolean | undefined)}
	{#if set}<span class="chip is-ok"><Icon name="check" />Configured</span>{/if}
{/snippet}

<div class="page-head">
	<div>
		<h1 class="page-title">Settings</h1>
		<p class="page-sub">Alerts, storage, capture, credentials and display for this NetTap.</p>
	</div>
</div>

<div class="tabs-scroll">
	<Pills options={TABS} bind:value={activeTab} ariaLabel="Settings sections" mode="tabs" idPrefix="settings" />
</div>

<div class="grid" role="tabpanel" id="settings-panel-{activeTab}" aria-labelledby="settings-tab-{activeTab}" tabindex="0">
	{#if activeTab === 'notifications'}
		<Card title="Notification preferences" sub="Which alerts reach you · by email and webhook" class="c-12">
			<div class="stack">
				{#if notifLoadFailed}
					{@render feedback('Could not load the current notification settings, so saving is off. Reload the page to try again.', true)}
				{/if}
				{@render feedback(notifMessage, notifError)}

				<div class="form-grid">
					<div class="field">
						<label class="label" for="severity-threshold">Alert severity threshold</label>
						<select class="select" id="severity-threshold" bind:value={severityThreshold}>
							{#each severityOptions as opt (opt.value)}
								<option value={opt.value}>{opt.label}</option>
							{/each}
						</select>
						<p class="field-help">Only notify for alerts at or above this severity level.</p>
					</div>
					<div class="field">
						<label class="label" for="webhook-url">Webhook URL</label>
						<input class="input mono" id="webhook-url" type="url" bind:value={webhookUrl} placeholder="https://hooks.example.com/nettap" />
						<p class="field-help">POST JSON payloads will be sent to this URL for each alert.</p>
					</div>
				</div>

				<div class="switch-row">
					<input type="checkbox" role="switch" class="switch" id="email-toggle" bind:checked={emailEnabled} aria-describedby="email-toggle-help" />
					<div>
						<label class="label" for="email-toggle">Enable email alerts</label>
						<p class="field-help" id="email-toggle-help">Send alert notifications to the email address below. Requires SMTP to be configured in API keys.</p>
					</div>
				</div>

				{#if emailEnabled}
					<div class="form-grid">
						<div class="field">
							<label class="label" for="email-address">Recipient email</label>
							<input class="input" id="email-address" type="email" bind:value={emailAddress} placeholder="admin@example.com" />
						</div>
					</div>
				{/if}

				<div class="form-actions">
					<button class="btn" type="button" onclick={sendTestNotification} disabled={testingSending}>
						{testingSending ? 'Sending…' : 'Send test notification'}
					</button>
					<button class="btn primary" type="button" onclick={saveNotifications} disabled={notifSaving || notifLoadFailed}>
						{notifSaving ? 'Saving…' : 'Save notification settings'}
					</button>
				</div>
				{@render feedback(testMessage, testError)}
			</div>
		</Card>
	{:else if activeTab === 'retention'}
		<!-- OLD CODE: sub="Storage status · read when this page opened" (NET-192 PR 4: the top bar's Refresh reads it again) -->
		<Card title="Retention health" sub="Storage status · read when the page opened or was refreshed" class="c-4">
			{#snippet actions()}
				{#if !storageLoading}
					<!-- OLD CODE START — no unknown state
					{retentionHealth.status === 'healthy' ? 'Healthy' : retentionHealth.status === 'attention' ? 'Attention' : 'Problem'}
					OLD CODE END -->
					<span class={['chip', { healthy: 'is-ok', attention: 'is-warn', problem: 'is-bad', unknown: '' }[retentionHealth.status]]}>
						{{ healthy: 'Healthy', attention: 'Attention', problem: 'Problem', unknown: 'Unknown' }[retentionHealth.status]}
					</span>
				{/if}
			{/snippet}
			{#if storageLoading}
				<CardState state="loading" title="Loading the storage status" />
			{:else if storageStatusFailed && ilmStatus === null && lastPruneAt === null}
				<CardState state="error" title={loadFailed('the storage status')} message="Check that NetTap is running on the System page, then reload." />
			{:else}
				{#if storageStatusFailed}
					<!-- OLD CODE: {@render feedback(loadFailed('the storage status', true), true)} (a red role="alert" box; stale figures are an amber status, NET-192 PR 4) -->
					<p class="notice is-warn" role="status"><Icon name="warn" /><span>{loadFailed('the storage status', true)}</span></p>
				{/if}
				<dl class="facts flush">
					<dt>ILM policies</dt>
					<dd>
						{#if ilmStatus === null}
							<span class="dim">Not reported</span>
						{:else if retentionHealth.ilmPending}
							<span class="chip">Syncing…</span>
						{:else if retentionHealth.ilmOk}
							<!-- OLD CODE START — 2026-11-02: read "All 1 synced" with one policy
							<span style="color: var(--green);">&#x2713; All {Object.keys(ilmStatus.policies).length || 3} synced</span>
							OLD CODE END -->
							{@const policyCount = Object.keys(ilmStatus.policies).length}
							<span class="chip is-ok"><Icon name="check" />{policyCount === 1 ? 'Policy synced' : `${policyCount || 'All'} policies synced`}</span>
						{:else}
							<span class="chip is-bad"><Icon name="warn" />Out of sync</span>
						{/if}
					</dd>
					<dt>Disk usage</dt>
					<dd>
						{#if diskUsage !== null}
							<span class="num">{diskUsage}%</span> <span class="dim">· warning at {retentionConfig.disk_threshold}%</span>
						{:else}
							<span class="dim">Unavailable</span>
						{/if}
					</dd>
					<dt>Last prune</dt>
					<dd>
						{#if lastPruneAt}
							<span class="num">{timeAgo(lastPruneAt)}</span>
						{:else}
							<span class="dim">Never (daemon starting…)</span>
						{/if}
					</dd>
				</dl>
				{#if diskUsage !== null}
					<div class="meter-row"><Meter value={diskUsage} label="Disk used" /></div>
				{/if}
			{/if}
		</Card>

		<Card title="Data retention policy" sub="Days kept per tier · disk thresholds in %" class="c-8">
			<div class="stack">
				{#if retentionLoad === 'failed'}
					{@render feedback('Could not load the current retention settings, so saving is off. Reload the page to try again.', true)}
				{/if}
				{@render feedback(retentionMessage, retentionError)}

				<div class="form-grid">
					<div class="field">
						<!-- OLD CODE START — 2026-11-02: Malcolm writes Zeek and Suricata to one daily
						     arkime_sessions3 index, so this setting governs alerts too
						<label class="label" for="hot-days">Hot Tier (Zeek metadata)</label>
						OLD CODE END -->
						<label class="label" for="hot-days">Hot tier (Zeek metadata and Suricata alerts)</label>
						<div class="unit-field">
							<input class="input" id="hot-days" type="number" bind:value={retentionConfig.hot_days} min={7} max={365} />
							<span class="dim">days</span>
						</div>
						<p class="field-help">Zeek logs and Suricata alerts share one daily index, so both are deleted after this many days.</p>
					</div>
					<div class="field">
						<!-- OLD CODE START — 2026-11-02: no Malcolm index is warm; alerts follow the Hot tier
						<label class="label" for="warm-days">Warm Tier (Suricata alerts)</label>
						OLD CODE END -->
						<label class="label" for="warm-days">Warm tier (separate Suricata indices)</label>
						<div class="unit-field">
							<input class="input" id="warm-days" type="number" bind:value={retentionConfig.warm_days} min={7} max={730} />
							<span class="dim">days</span>
						</div>
						<p class="field-help">Applies only to separate <span class="mono">suricata-*</span> indices, which this install doesn't create. Alerts follow the Hot tier.</p>
					</div>
					<div class="field">
						<label class="label" for="cold-days">Cold tier (PCAP files)</label>
						<div class="unit-field">
							<input class="input" id="cold-days" type="number" bind:value={retentionConfig.cold_days} min={1} max={365} />
							<span class="dim">days</span>
						</div>
						<p class="field-help">Raw packet captures of all traffic. The oldest files also go once PCAP passes its share of the disk.</p>
					</div>
				</div>

				<div class="form-grid">
					<div class="field">
						<label class="label" for="disk-threshold">Disk warning threshold</label>
						<div class="unit-field">
							<input class="input" id="disk-threshold" type="number" bind:value={retentionConfig.disk_threshold} min={50} max={95} />
							<span class="dim">%</span>
						</div>
						<p class="field-help">Start pruning old data when disk usage exceeds this.</p>
					</div>
					<div class="field">
						<label class="label" for="emergency-threshold">Emergency threshold</label>
						<div class="unit-field">
							<input class="input" id="emergency-threshold" type="number" bind:value={retentionConfig.emergency_threshold} min={60} max={99} />
							<span class="dim">%</span>
						</div>
						<p class="field-help">Aggressive pruning regardless of tier when disk exceeds this.</p>
					</div>
				</div>

				<div class="form-actions">
					<button class="btn primary" type="button" onclick={saveRetention} disabled={retentionSaving || retentionLoad !== 'ok'}>
						{retentionSaving ? 'Saving…' : 'Save retention settings'}
					</button>
				</div>
			</div>
		</Card>

		<Card title="Manual data cleanup" sub="Deletes OpenSearch indices and PCAP files · cannot be undone" class="c-12">
			<div class="stack">
				<p class="field-help">Permanently delete OpenSearch indices and PCAP files older than a specified number of days to free up disk space.</p>
				{@render feedback(cleanupMessage, cleanupError)}

				<div class="inline-row">
					<span>Delete data older than</span>
					<div class="unit-field">
						<!-- OLD CODE START — editing the days left the old preview (and its Delete button) on screen
						<input class="input" type="number" bind:value={cleanupDays} min={1} max={3650} disabled={cleanupExecuting} />
						OLD CODE END -->
						<input
							class="input"
							type="number"
							aria-label="Delete data older than (days)"
							bind:value={cleanupDays}
							oninput={cancelCleanup}
							min={1}
							max={3650}
							disabled={cleanupExecuting || cleanupPreviewing}
						/>
						<span class="dim">days</span>
					</div>
					<button class="btn" type="button" onclick={handleCleanupPreview} disabled={cleanupPreviewing || cleanupExecuting || cleanupDays < 1}>
						{cleanupPreviewing ? 'Scanning…' : 'Preview cleanup'}
					</button>
				</div>

				{#if cleanupPreview}
					<section class="preview" aria-labelledby="cleanup-preview-title">
						<div class="preview-head">
							<h3 class="eyebrow" id="cleanup-preview-title">Cleanup preview</h3>
							<span class="dim">Data before {formatTime(cleanupPreview.cutoff_date, 'date')}</span>
						</div>
						<StatStrip
							stats={[
								{ key: 'indices', label: 'Indices', value: String(cleanupPreview.total_indices) },
								{ key: 'pcap', label: 'PCAP files', value: String(cleanupPreview.total_pcap_files) },
								{ key: 'freed', label: 'Space freed', value: formatBytes(cleanupPreview.estimated_freed_bytes) },
							]}
						/>

						{#if cleanupPreview.total_indices === 0 && cleanupPreview.total_pcap_files === 0}
							<p class="dim">No data found older than {cleanupPreviewDays} days.</p>
						{:else if !showCleanupConfirm}
							{@render feedback('This action is irreversible. Deleted data cannot be recovered.', true)}
							<div class="form-actions">
								<button class="btn" type="button" onclick={cancelCleanup}>Cancel</button>
								<button class="btn danger" type="button" onclick={() => (showCleanupConfirm = true)}>Delete data</button>
							</div>
						{:else}
							{@render feedback(
								`Are you sure? This will permanently delete ${cleanupPreview.total_indices} indices and ${cleanupPreview.total_pcap_files} PCAP files (${formatBytes(cleanupPreview.estimated_freed_bytes)}).`,
								true,
							)}
							<div class="form-actions">
								<button class="btn" type="button" onclick={cancelCleanup} disabled={cleanupExecuting}>Cancel</button>
								<button class="btn danger" type="button" onclick={handleCleanupExecute} disabled={cleanupExecuting}>
									{cleanupExecuting ? 'Deleting…' : 'Confirm delete'}
								</button>
							</div>
						{/if}
					</section>
				{/if}
			</div>
		</Card>
	{:else if activeTab === 'capture'}
		<!-- OLD CODE: sub="Packet capture container · file size in MB" (NET-166: netsniff-ng counts MiB) -->
		<Card title="PCAP capture" sub="Packet capture container · file size in MiB" class="c-12">
			{#if captureLoading}
				<CardState state="loading" title="Loading capture settings" />
			{:else if captureLoadFailed}
				<CardState state="error" title="Could not load the current capture settings, so changes are off." message="Reload the page to try again." />
			{:else}
				<div class="stack">
					{@render feedback(captureMessage, captureError)}
					<dl class="facts flush">
						<dt>Container status</dt>
						<dd>
							{#if captureContainerRunning}
								<span class="chip is-ok"><Icon name="check" />Running</span>
							{:else}
								<span class="chip">{captureContainerStatus}</span>
							{/if}
						</dd>
					</dl>

					<div class="switch-row">
						<!-- the API decides the state: the click is cancelled and the switch follows the answer -->
						<input
							type="checkbox"
							role="switch"
							class="switch"
							id="capture-toggle"
							checked={captureEnabled}
							disabled={captureToggling}
							aria-describedby="capture-toggle-help"
							onclick={(e) => {
								e.preventDefault();
								handleCaptureToggle();
							}}
						/>
						<div>
							<label class="label" for="capture-toggle">PCAP collection</label>
							<!-- OLD CODE START — claimed "capturing packets" even with the container stopped
							<span class="capture-toggle-label">{captureEnabled ? 'Enabled — capturing packets' : 'Disabled — no new captures'}</span>
							OLD CODE END -->
							<p class="state-line">
								{#if !captureEnabled}
									Disabled — no new captures
								{:else if captureContainerRunning}
									Enabled — capturing packets
								{:else if captureContainerStatus === 'unknown'}
									Enabled — capture status unknown
								{:else}
									Enabled — capture container not running
								{/if}
							</p>
							<p class="field-help" id="capture-toggle-help">When disabled, the capture container is stopped. Existing PCAP files remain accessible.</p>
						</div>
					</div>

					<div class="form-grid">
						<div class="field">
							<label class="label" for="max-file-size">Max file size</label>
							<div class="unit-field">
								<input class="input" id="max-file-size" type="number" bind:value={captureMaxFileSize} min={10} max={10000} />
								<!-- OLD CODE: <span class="dim">MB</span> (NET-166: netsniff-ng's PCAP_ROTATE_MB counts mebibytes) -->
								<span class="dim">MiB</span>
							</div>
							<!-- OLD CODE START — 2026-11-02: the 100 MB default was never what netsniff used
							<p class="field-help">Individual PCAP files rotate at this size. Default: 100 MB. Range: 10–10,000 MB.</p>
							OLD CODE END -->
							<!-- OLD CODE START — 2026-11-06 (NET-166): said MB, but netsniff-ng counts MiB
							<p class="field-help">
								A new file starts at this size{captureRotateMinutes ? ` or every ${captureRotateMinutes} minutes, whichever comes first` : ''}. Range: 10–10,000 MB.
							</p>
							OLD CODE END -->
							<p class="field-help">
								A new file starts at this size{captureRotateMinutes ? ` or every ${captureRotateMinutes} minutes, whichever comes first` : ''}. Range: 10–10,000 MiB.
								1 MiB is 1,048,576 bytes, so a 256 MiB file shows as 268.4 MB on the PCAP page.
							</p>
						</div>
					</div>

					<div class="form-actions">
						<button class="btn primary" type="button" onclick={saveCaptureSettings} disabled={captureSaving}>
							{captureSaving ? 'Saving…' : 'Save capture settings'}
						</button>
					</div>
				</div>
			{/if}
		</Card>
	{:else if activeTab === 'api-keys'}
		<Card title="API keys and credentials" sub="Stored on this NetTap · never shown after saving" class="c-12">
			{#if apiKeysLoading}
				<CardState state="loading" title="Loading API key status" />
			{:else}
				<div class="stack">
					<p class="field-help">
						Configure external service credentials. Keys are stored securely on disk and never displayed after saving.
						Fields marked "Configured" already have a value saved: leave the input blank to keep the existing value.
					</p>
					{@render feedback(apiKeysMessage, apiKeysError)}

					<section class="key-group" aria-labelledby="keys-geoip">
						<h3 class="eyebrow" id="keys-geoip">GeoIP lookups</h3>
						<div class="form-grid">
							<div class="field">
								<div class="label-row"><label class="label" for="maxmind-key">MaxMind licence key</label>{@render configured(apiKeysStatus['MAXMIND_LICENSE_KEY'])}</div>
								<input
									class="input mono"
									id="maxmind-key"
									type="password"
									bind:value={apiKeyValues['MAXMIND_LICENSE_KEY']}
									placeholder={apiKeysStatus['MAXMIND_LICENSE_KEY'] ? 'Leave blank to keep current value' : 'Enter MaxMind licence key'}
								/>
								<p class="field-help">Required for GeoIP map visualisations. Get a free key at <a class="link" href="https://www.maxmind.com/en/geolite2/signup" target="_blank" rel="noopener">maxmind.com</a>.</p>
							</div>
						</div>
					</section>

					<section class="key-group" aria-labelledby="keys-ids">
						<h3 class="eyebrow" id="keys-ids">IDS rules</h3>
						<!-- OLD CODE START — NET-191 slice 2: this key was saved to the daemon's env file and never reached Suricata.
						     The ET Pro code has one place now, Settings › Suricata rules.
						<div class="form-grid">
							<div class="field">
								<div class="label-row"><label class="label" for="et-pro-key">Emerging Threats Pro key</label>{@render configured(apiKeysStatus['SURICATA_ET_PRO_KEY'])}</div>
								<input
									class="input mono"
									id="et-pro-key"
									type="password"
									bind:value={apiKeyValues['SURICATA_ET_PRO_KEY']}
									placeholder={apiKeysStatus['SURICATA_ET_PRO_KEY'] ? 'Leave blank to keep current value' : 'Enter ET Pro key (optional)'}
								/>
								<p class="field-help">Optional. Enables Proofpoint's commercial Suricata ruleset. Free ET Open rules are used by default.</p>
							</div>
						</div>
						OLD CODE END -->
						<p class="field-help">
							The optional Emerging Threats Pro code is set in <a class="link" href="/settings/suricata-rules">Settings › Suricata rules</a>,
							which checks it with Proofpoint before Suricata uses it.
						</p>
					</section>

					<section class="key-group" aria-labelledby="keys-smtp">
						<h3 class="eyebrow" id="keys-smtp">SMTP (email alerts)</h3>
						<p class="field-help">Required for email notifications. Configure your SMTP server details below, then enable email alerts in the Notifications tab.</p>
						<div class="form-grid">
							<div class="field">
								<div class="label-row"><label class="label" for="smtp-host">SMTP host</label>{@render configured(apiKeysStatus['SMTP_HOST'])}</div>
								<input class="input mono" id="smtp-host" type="text" bind:value={apiKeyValues['SMTP_HOST']} placeholder={apiKeysStatus['SMTP_HOST'] ? 'Leave blank to keep current' : 'smtp.gmail.com'} />
								<p class="field-help">SMTP server hostname.</p>
							</div>
							<div class="field">
								<div class="label-row"><label class="label" for="smtp-port">SMTP port</label>{@render configured(apiKeysStatus['SMTP_PORT'])}</div>
								<input class="input mono" id="smtp-port" type="text" bind:value={apiKeyValues['SMTP_PORT']} placeholder={apiKeysStatus['SMTP_PORT'] ? 'Leave blank to keep current' : '587'} />
								<p class="field-help">587 for STARTTLS, 465 for SSL/TLS.</p>
							</div>
							<div class="field">
								<div class="label-row"><label class="label" for="smtp-username">SMTP username</label>{@render configured(apiKeysStatus['SMTP_USERNAME'])}</div>
								<input class="input" id="smtp-username" type="text" bind:value={apiKeyValues['SMTP_USERNAME']} placeholder={apiKeysStatus['SMTP_USERNAME'] ? 'Leave blank to keep current' : 'user@example.com'} />
								<p class="field-help">Your SMTP login username or email.</p>
							</div>
							<div class="field">
								<div class="label-row"><label class="label" for="smtp-password">SMTP password</label>{@render configured(apiKeysStatus['SMTP_PASSWORD'])}</div>
								<input class="input" id="smtp-password" type="password" bind:value={apiKeyValues['SMTP_PASSWORD']} placeholder={apiKeysStatus['SMTP_PASSWORD'] ? 'Leave blank to keep current' : 'App password or SMTP password'} />
								<p class="field-help">For Gmail, use an App Password (not your account password).</p>
							</div>
							<div class="field">
								<div class="label-row"><label class="label" for="smtp-sender">Sender email</label>{@render configured(apiKeysStatus['SMTP_SENDER_EMAIL'])}</div>
								<input class="input" id="smtp-sender" type="email" bind:value={apiKeyValues['SMTP_SENDER_EMAIL']} placeholder={apiKeysStatus['SMTP_SENDER_EMAIL'] ? 'Leave blank to keep current' : 'nettap@example.com'} />
								<p class="field-help">The "From" address on alert emails.</p>
							</div>
						</div>
					</section>

					<section class="key-group" aria-labelledby="keys-webhook">
						<h3 class="eyebrow" id="keys-webhook">Webhook</h3>
						<div class="form-grid">
							<div class="field">
								<div class="label-row"><label class="label" for="webhook-url-keys">Webhook URL</label>{@render configured(apiKeysStatus['WEBHOOK_URL'])}</div>
								<input
									class="input mono"
									id="webhook-url-keys"
									type="url"
									bind:value={apiKeyValues['WEBHOOK_URL']}
									placeholder={apiKeysStatus['WEBHOOK_URL'] ? 'Leave blank to keep current' : 'https://hooks.slack.com/services/…'}
								/>
								<p class="field-help">Also configurable in the Notifications tab. JSON alert payloads are POSTed here.</p>
							</div>
						</div>
					</section>

					<div class="form-actions">
						<button class="btn primary" type="button" onclick={saveApiKeys} disabled={apiKeysSaving}>
							{apiKeysSaving ? 'Saving…' : 'Save API keys'}
						</button>
					</div>
				</div>
			{/if}
		</Card>
	{:else if activeTab === 'network'}
		<Card title="Excluded IPs" sub="Hidden from device views · still in logs, alerts and connections" class="c-12">
			{#if networkLoading}
				<CardState state="loading" title="Loading the excluded IP list" />
			{:else if networkLoadFailed}
				<CardState state="error" title="Could not load the excluded IP list, so changes are off." message="Reload the page to try again." />
			{:else}
				<div class="stack">
					<p class="field-help">
						IPs in this list are hidden from device-centric views (Devices, Top Talkers, Risk Scores) but remain visible in Log Explorer, Alerts, and raw connection data.
						Useful for filtering out your ISP gateway's public IP or infrastructure addresses that appear on every connection.
					</p>
					{@render feedback(networkMessage, networkError)}

					<div class="field">
						<label class="label" for="excluded-ip-new">IP address to exclude</label>
						<div class="inline-row">
							<input
								class="input mono"
								id="excluded-ip-new"
								type="text"
								bind:value={newExcludedIp}
								placeholder="e.g. 99.10.70.92"
								onkeydown={(e) => {
									if (e.key === 'Enter') addExcludedIp();
								}}
							/>
							<button class="btn" type="button" onclick={addExcludedIp}>Add</button>
						</div>
					</div>

					{#if excludedIps.length === 0}
						<p class="dim">No IPs excluded. All IPs appear in device views.</p>
					{:else}
						<ul class="ip-list" aria-label="Excluded IPs">
							{#each excludedIps as ip (ip)}
								<li>
									<span class="mono">{ip}</span>
									<button class="icon-btn ghost" type="button" aria-label="Remove {ip}" onclick={() => removeExcludedIp(ip)}><Icon name="close" /></button>
								</li>
							{/each}
						</ul>
					{/if}

					<div class="form-actions">
						<button class="btn primary" type="button" onclick={saveExcludedIps} disabled={networkSaving}>
							{networkSaving ? 'Saving…' : 'Save excluded IPs'}
						</button>
					</div>
				</div>
			{/if}
		</Card>
	{:else if activeTab === 'integrations'}
		<Card title="UniFi controller" sub="Device names, models and networks from UniFi · API key sign-in" class="c-12">
			{#snippet actions()}
				{#if unifiConfigured}
					<span class={['chip', unifiConnected ? 'is-ok' : 'is-bad']}>
						<Icon name={unifiConnected ? 'check' : 'warn'} />{unifiConnected ? 'Connected' : 'Disconnected'}
					</span>
				{/if}
			{/snippet}
			{#if unifiLoading}
				<CardState state="loading" title="Loading UniFi status" />
			{:else}
				<div class="stack">
					<p class="field-help">
						Connect to your UniFi controller to enrich device data with friendly names, models, and network assignments. Uses API key authentication (UniFi OS 10.2.93+).
					</p>
					{@render feedback(unifiMessage, unifiError)}
					{#if unifiStatusFailed}
						<div class="notice is-warn" role="status"><Icon name="warn" />{loadFailed('the UniFi status')} The controller may already be set up.</div>
					{/if}

					{#if unifiConfigured && (unifiCacheCounts || unifiLastPoll)}
						<StatStrip
							stats={[
								...(unifiCacheCounts
									? [
											{ key: 'clients', label: 'Cached clients', value: String(unifiCacheCounts.clients) },
											{ key: 'devices', label: 'Cached devices', value: String(unifiCacheCounts.devices) },
										]
									: []),
								...(unifiLastPoll ? [{ key: 'poll', label: 'Last poll', value: formatUnifiPollTime(unifiLastPoll) }] : []),
							]}
						/>
					{/if}

					<div class="form-grid">
						<div class="field">
							<label class="label" for="unifi-url">Controller URL</label>
							<input class="input mono" id="unifi-url" type="url" bind:value={unifiControllerUrl} placeholder="https://192.168.1.1" />
							<p class="field-help">Full URL to your UniFi controller (e.g. https://192.168.1.1 or https://unifi.local:8443).</p>
						</div>

						<div class="field">
							<div class="label-row"><label class="label" for="unifi-api-key">API key</label>{@render configured(unifiConfigured)}</div>
							<input
								class="input mono"
								id="unifi-api-key"
								type="password"
								bind:value={unifiApiKey}
								placeholder={unifiConfigured ? 'Leave blank to keep current key' : 'Paste your UniFi API key'}
								autocomplete="off"
								spellcheck="false"
							/>
							<p class="field-help">
								Generate an API key in UniFi OS: Settings · System · Advanced · API Key.
								{#if unifiConfigured}
									Leave blank to keep the currently saved key.
								{/if}
							</p>
						</div>

						<div class="field">
							<label class="label" for="unifi-site">Site</label>
							{#if unifiSites.length > 0}
								<select class="select" id="unifi-site" bind:value={unifiSiteId}>
									<option value="">Select a site…</option>
									{#each unifiSites as site (site.id)}
										<option value={site.id}>{site.desc || site.name || site.id}</option>
									{/each}
								</select>
								<p class="field-help">Select which UniFi site to poll for device data.</p>
							{:else if unifiSitesLoading}
								<p class="field-help">Loading sites…</p>
							{:else}
								<input class="input mono" id="unifi-site" type="text" bind:value={unifiSiteId} placeholder="default" />
								<p class="field-help">Enter a site ID manually, or save and test the connection to auto-discover sites. Most setups use "default".</p>
							{/if}
						</div>
					</div>

					<div class="form-actions">
						{#if unifiConfigured}
							<button class="btn" type="button" onclick={testUnifiConnection} disabled={unifiTesting || unifiSaving}>
								{unifiTesting ? 'Testing…' : 'Test connection'}
							</button>
						{/if}
						<button class="btn primary" type="button" onclick={saveUnifiConfig} disabled={unifiSaving || unifiTesting}>
							{unifiSaving ? 'Saving…' : 'Save configuration'}
						</button>
					</div>
				</div>
			{/if}
		</Card>
	{:else if activeTab === 'display'}
		<!-- OLD CODE: sub="Theme, refresh and time settings · saved in this browser" (NET-195: the refresh and timezone controls are gone) -->
		<Card title="Display preferences" sub="Theme and the default time range · saved in this browser" class="c-12">
			<div class="stack">
				<ThemePicker />
				{@render feedback(displayMessage, displayError)}

				<div class="form-grid">
					<!-- OLD CODE START — NET-195: no page read these; each page owns its Auto toggle, and times are browser-local
					<div class="field">
						<label class="label" for="auto-refresh">Auto-refresh interval</label>
						<select class="select" id="auto-refresh" bind:value={autoRefresh}>
							<option value="0">Off</option>
							<option value="10">10 seconds</option>
							<option value="30">30 seconds</option>
							<option value="60">1 minute</option>
							<option value="300">5 minutes</option>
						</select>
						<p class="field-help">How often dashboards auto-refresh data.</p>
					</div>
					<div class="field">
						<label class="label" for="timezone">Timezone</label>
						<select class="select" id="timezone" bind:value={timezone}>
							<option value="utc">UTC</option>
							<option value="local">Local (browser)</option>
						</select>
						<p class="field-help">Timezone used for displaying timestamps.</p>
					</div>
					OLD CODE END -->
					<div class="field">
						<label class="label" for="default-range">Default time range</label>
						<!-- OLD CODE: bind:value={defaultTimeRange} (NET-195: saved as defaultRange, '' for each page's own) -->
						<select class="select" id="default-range" bind:value={defaultRange}>
							<!-- OLD CODE START — NET-192 PR 4: one range set across the app (1h 6h 24h 7d 30d)
							<option value="15m">Last 15 minutes</option>
							<option value="1h">Last 1 hour</option>
							<option value="4h">Last 4 hours</option>
							<option value="24h">Last 24 hours</option>
							<option value="7d">Last 7 days</option>
							OLD CODE END -->
							<!-- OLD CODE START — NET-195: from DRILL_RANGES, after "Each page's own"
							<option value="1h">Last hour</option>
							<option value="6h">Last 6 hours</option>
							<option value="24h">Last 24 hours</option>
							<option value="7d">Last 7 days</option>
							<option value="30d">Last 30 days</option>
							OLD CODE END -->
							<option value="">Each page's own (most open on 24 hours)</option>
							{#each DRILL_RANGES as r (r.value)}
								<option value={r.value}>{r.words.charAt(0).toUpperCase() + r.words.slice(1)}</option>
							{/each}
						</select>
						<!-- OLD CODE: <p class="field-help">Default time window for traffic and alert views.</p> (NET-195) -->
						<p class="field-help">
							The window traffic, alert and device pages open on. A link from a figure still opens on that figure's window.
							PCAP and Certificates keep their own (1 hour, 7 days).
						</p>
					</div>
				</div>

				<div class="form-actions">
					<button class="btn primary" type="button" onclick={saveDisplay} disabled={displaySaving}>
						{displaySaving ? 'Saving…' : 'Save display settings'}
					</button>
				</div>
			</div>
		</Card>
	{:else if activeTab === 'about'}
		<!-- OLD CODE: sub="This appliance · read when this page opened" (NET-192 PR 4: the top bar's Refresh reads it again) -->
		<Card title="About NetTap" sub="This appliance · read when the page opened or was refreshed" class="c-6">
			<dl class="facts flush">
				<dt>Version</dt>
				<dd class="mono">{version}</dd>
				<dt>Uptime</dt>
				<dd class="num">{uptime}</dd>
				<dt>Licence</dt>
				<!-- OLD CODE: Apache 2.0 (wrong since the licence switch; the repo's LICENSE is the NetTap Personal Use License) -->
				<dd>NetTap Personal Use License</dd>
				<dt>Stack</dt>
				<!-- OLD CODE: Zeek + Suricata + Arkime + OpenSearch (Arkime off by default since 2026-11-02, #44) -->
				<dd>Zeek + Suricata + OpenSearch</dd>
				{#if buildInfo}
					<dt>Build</dt>
					<dd class="mono">{buildInfo}</dd>
				{/if}
			</dl>
			<div class="form-actions">
				<a href="https://github.com/EliasMarine/NetTap" target="_blank" rel="noopener" class="btn">GitHub repository</a>
				<a href="https://github.com/EliasMarine/NetTap/wiki" target="_blank" rel="noopener" class="btn">Documentation</a>
			</div>
		</Card>
	{/if}
</div>

<style>
	/* Eight tabs overflow a phone: the tab row scrolls on its own, never the page */
	.tabs-scroll {
		overflow-x: auto;
		padding: var(--sp-1);
		margin: calc(var(--sp-1) * -1);
	}

	.grid:focus-visible {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
		border-radius: var(--r-lg);
	}

	.facts.flush {
		border-top: 0;
		padding-top: 0;
	}

	.switch-row {
		display: flex;
		align-items: flex-start;
		gap: var(--sp-3);
	}

	.switch-row .label {
		margin-bottom: 0;
	}

	.state-line {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.label-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--sp-2);
	}

	.label-row .label {
		margin-bottom: 0;
	}

	.unit-field,
	.inline-row {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		flex-wrap: wrap;
	}

	.unit-field .input {
		width: 120px;
	}

	.inline-row .input {
		flex: 1 1 220px;
		max-width: 360px;
	}

	.meter-row {
		margin-top: var(--sp-4);
	}

	.preview {
		display: flex;
		flex-direction: column;
		gap: var(--sp-4);
		padding: var(--sp-4);
		border-radius: var(--r-md);
		background: var(--surface-2);
		border: 1px solid var(--line);
	}

	.preview-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--sp-3);
		flex-wrap: wrap;
		font-size: var(--text-xs);
	}

	.key-group {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
		padding-top: var(--sp-4);
		border-top: 1px solid var(--line);
	}

	.ip-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-2);
	}

	.ip-list li {
		display: inline-flex;
		align-items: center;
		gap: var(--sp-1);
		padding-left: var(--sp-3);
		border-radius: var(--r-pill);
		background: var(--surface-2);
		border: 1px solid var(--line);
		font-size: var(--text-sm);
	}

	/* The system has no destructive button: the word carries it, the colour backs it up */
	.btn.danger {
		color: var(--sev-critical);
	}
</style>
