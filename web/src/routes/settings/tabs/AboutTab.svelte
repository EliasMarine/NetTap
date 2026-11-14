<!--
  Settings › About (NET-273: moved from the Settings page): the daemon's version and uptime, read
  through the top bar's Refresh.
-->
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { registerPageRefresh, type LoadGuard, type LoadResult } from '$lib/stores/pageRefresh';
	import { formatDuration } from '$lib/utils/tshark-helpers';
	import Card from '$lib/components/ui/Card.svelte';

	// --- About state ---
	let version = $state('…');
	let uptime = $state('…');
	// OLD CODE: let buildInfo = $state('…'); (S11: the daemon sends no build, so it fell back to "Development build")
	/** The build the daemon reports; null hides the row rather than claim one. */
	let buildInfo = $state<string | null>(null);

	/** True when both reads answered (the loader's outcome). */
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

	/** The top bar's Refresh (NET-273: About's half of the page's old loader). */
	async function load(guard: LoadGuard): Promise<LoadResult> {
		const g = guard.begin();
		// shortcut: the reads write their rows unguarded; they take no range or filter, so an older
		// reply answers the same question. Copy the query into locals if they gain one.
		const ok = await loadAbout();
		if (!guard.current(g)) return 'skipped';
		return ok ? 'ok' : 'failed';
	}

	const refresh = registerPageRefresh(load);
	onDestroy(refresh.unregister);
	onMount(() => void refresh.run());
</script>

<div class="grid">
	<!-- OLD CODE: sub="This appliance · read when this page opened" (NET-192 PR 4: the top bar's Refresh reads it again) -->
	<Card title="About NetTap" sub="This appliance · read when the page opened or was refreshed" class="c-6">
		<dl class="facts flush">
			<dt>Version</dt>
			<dd class="mono">{version}</dd>
			<dt>Uptime</dt>
			<dd class="num">{uptime}</dd>
			<dt>Licence</dt>
			<dd>GNU GPLv3 (version 3 only)</dd>
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
</div>
