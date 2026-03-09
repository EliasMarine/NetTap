<script lang="ts">
	/**
	 * Suricata Rule Management — IDS rule sources, updates, custom rules.
	 *
	 * Manage rule feeds (ET Open, abuse.ch, tgreen, etc.), trigger updates,
	 * set auto-update schedule, upload custom rules, and configure commercial
	 * license keys (ET Pro, Snort Subscriber).
	 */

	import {
		getRuleSources,
		enableRuleSource,
		disableRuleSource,
		updateRulesNow,
		getRuleStats,
		getUpdateSchedule,
		setUpdateSchedule,
		uploadCustomRules,
		getCustomRules,
		configureCommercial,
		getCommercialConfig,
		type RuleSource,
		type RuleStats,
		type UpdateSchedule,
		type CommercialConfig,
	} from '$lib/api/suricata-rules';

	// State
	let sources = $state<RuleSource[]>([]);
	let stats = $state<RuleStats | null>(null);
	let schedule = $state<UpdateSchedule>({ interval: 'daily', enabled: true });
	let commercialConfig = $state<CommercialConfig>({ configured: false });
	let lastUpdate = $state<string | null>(null);
	let loading = $state(true);
	let updating = $state(false);
	let message = $state('');
	let messageType = $state<'success' | 'error'>('success');

	// Custom rules
	let customRulesContent = $state('');
	let savingCustomRules = $state(false);

	// Commercial form
	let showCommercialForm = $state(false);
	let commercialType = $state('etpro');
	let commercialKey = $state('');
	let savingCommercial = $state(false);

	// Toggling state (track which source is being toggled)
	let togglingSource = $state('');

	function showMessage(text: string, type: 'success' | 'error' = 'success') {
		message = text;
		messageType = type;
		setTimeout(() => { message = ''; }, 5000);
	}

	async function loadData() {
		loading = true;
		try {
			const [sourcesRes, statsRes, scheduleRes, customRes, commRes] = await Promise.all([
				getRuleSources(),
				getRuleStats(),
				getUpdateSchedule(),
				getCustomRules(),
				getCommercialConfig(),
			]);
			sources = sourcesRes.sources;
			lastUpdate = sourcesRes.last_update;
			stats = statsRes;
			schedule = scheduleRes;
			customRulesContent = customRes;
			commercialConfig = commRes;
		} catch (err) {
			showMessage('Failed to load rule data', 'error');
		} finally {
			loading = false;
		}
	}

	async function toggleSource(source: RuleSource) {
		togglingSource = source.id;
		try {
			const success = source.enabled
				? await disableRuleSource(source.id)
				: await enableRuleSource(source.id);
			if (success) {
				source.enabled = !source.enabled;
				showMessage(`${source.id} ${source.enabled ? 'enabled' : 'disabled'}`);
			} else {
				showMessage(`Failed to toggle ${source.id}`, 'error');
			}
		} catch {
			showMessage(`Error toggling ${source.id}`, 'error');
		} finally {
			togglingSource = '';
		}
	}

	async function handleUpdateNow() {
		updating = true;
		try {
			const result = await updateRulesNow();
			if (result.success) {
				showMessage('Rules updated and reloaded successfully');
				await loadData();
			} else {
				showMessage('Rule update failed: ' + result.output.slice(0, 200), 'error');
			}
		} catch {
			showMessage('Failed to trigger rule update', 'error');
		} finally {
			updating = false;
		}
	}

	async function handleScheduleChange(e: Event) {
		const target = e.target as HTMLSelectElement;
		const interval = target.value;
		try {
			schedule = await setUpdateSchedule(interval);
			showMessage(`Update schedule set to ${interval}`);
		} catch {
			showMessage('Failed to update schedule', 'error');
		}
	}

	async function handleSaveCustomRules() {
		savingCustomRules = true;
		try {
			const result = await uploadCustomRules(customRulesContent);
			if (result.success) {
				showMessage(`Saved ${result.rules_written} custom rules`);
			} else {
				showMessage('Failed to save custom rules', 'error');
			}
		} catch {
			showMessage('Error saving custom rules', 'error');
		} finally {
			savingCustomRules = false;
		}
	}

	async function handleSaveCommercial() {
		if (!commercialKey || commercialKey.length < 8) {
			showMessage('License key must be at least 8 characters', 'error');
			return;
		}
		savingCommercial = true;
		try {
			const result = await configureCommercial(commercialType, commercialKey);
			if (result.success) {
				showMessage(`${commercialType === 'etpro' ? 'ET Pro' : 'Snort Subscriber'} configured`);
				commercialConfig = await getCommercialConfig();
				showCommercialForm = false;
				commercialKey = '';
			} else {
				showMessage('Failed to configure commercial source', 'error');
			}
		} catch {
			showMessage('Error configuring commercial source', 'error');
		} finally {
			savingCommercial = false;
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return 'Never';
		try {
			return new Date(iso).toLocaleString();
		} catch {
			return iso;
		}
	}

	// Load data on mount
	$effect(() => {
		loadData();
	});
</script>

<svelte:head>
	<title>Suricata Rules | NetTap Settings</title>
</svelte:head>

<div class="page-container">
	<header class="page-header">
		<div>
			<h1>Suricata IDS Rules</h1>
			<p class="subtitle">Manage threat detection rule sources, updates, and custom rules</p>
		</div>
		<a href="/settings" class="back-link">Back to Settings</a>
	</header>

	{#if message}
		<div class="message" class:error={messageType === 'error'} class:success={messageType === 'success'}>
			{message}
		</div>
	{/if}

	{#if loading}
		<div class="loading">Loading rule configuration...</div>
	{:else}
		<!-- Hero card -->
		<div class="hero-card">
			<div class="hero-stats">
				<div class="stat">
					<span class="stat-value">{stats?.enabled_sources ?? 0}</span>
					<span class="stat-label">Active Sources</span>
				</div>
				<div class="stat">
					<span class="stat-value">{stats?.total_sources ?? 0}</span>
					<span class="stat-label">Total Sources</span>
				</div>
				<div class="stat">
					<span class="stat-value">{formatDate(lastUpdate)}</span>
					<span class="stat-label">Last Updated</span>
				</div>
			</div>
			<div class="hero-actions">
				<button class="btn btn-primary" onclick={handleUpdateNow} disabled={updating}>
					{updating ? 'Updating...' : 'Update Rules Now'}
				</button>
			</div>
		</div>

		<!-- Rule Sources Table -->
		<section class="card">
			<h2>Rule Sources</h2>
			<p class="section-desc">Enable or disable community rule feeds. Changes take effect on next update.</p>
			<table class="sources-table">
				<thead>
					<tr>
						<th>Source</th>
						<th>Description</th>
						<th>Status</th>
					</tr>
				</thead>
				<tbody>
					{#each sources as source}
						<tr>
							<td class="source-id"><code>{source.id}</code></td>
							<td class="source-desc">{source.description}</td>
							<td>
								<button
									class="toggle-btn"
									class:enabled={source.enabled}
									onclick={() => toggleSource(source)}
									disabled={togglingSource === source.id}
								>
									{togglingSource === source.id ? '...' : source.enabled ? 'Enabled' : 'Disabled'}
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</section>

		<!-- Update Schedule -->
		<section class="card">
			<h2>Update Schedule</h2>
			<p class="section-desc">How often should rules be automatically updated from upstream sources?</p>
			<div class="schedule-row">
				<label for="schedule-select">Auto-update interval:</label>
				<select id="schedule-select" value={schedule.interval} onchange={handleScheduleChange}>
					<option value="daily">Daily</option>
					<option value="weekly">Weekly</option>
					<option value="manual">Manual only</option>
				</select>
				<span class="schedule-status">
					{schedule.enabled ? 'Auto-updates enabled' : 'Auto-updates disabled (manual only)'}
				</span>
			</div>
		</section>

		<!-- Custom Rules -->
		<section class="card">
			<h2>Custom Rules</h2>
			<p class="section-desc">
				Add your own Suricata rules. One rule per line. Lines starting with # are comments.
			</p>
			<textarea
				class="custom-rules-editor"
				bind:value={customRulesContent}
				placeholder='alert tcp any any -> any any (msg:"Custom rule"; sid:9999001; rev:1;)'
				rows="8"
			></textarea>
			<button
				class="btn btn-secondary"
				onclick={handleSaveCustomRules}
				disabled={savingCustomRules}
			>
				{savingCustomRules ? 'Saving...' : 'Save Custom Rules'}
			</button>
		</section>

		<!-- Commercial License -->
		<section class="card">
			<h2>Commercial Rule Sources</h2>
			<p class="section-desc">
				Configure ET Pro or Snort Subscriber license keys for premium rule feeds.
			</p>
			{#if commercialConfig.configured}
				<div class="commercial-status">
					<span>Active: <strong>{commercialConfig.source_type === 'etpro' ? 'ET Pro' : 'Snort Subscriber'}</strong></span>
					<span>Key: <code>{commercialConfig.license_key_masked}</code></span>
					<span>Configured: {formatDate(commercialConfig.configured_at ?? null)}</span>
				</div>
			{/if}
			{#if showCommercialForm}
				<div class="commercial-form">
					<div class="form-group">
						<label for="commercial-type">Source Type:</label>
						<select id="commercial-type" bind:value={commercialType}>
							<option value="etpro">ET Pro (Proofpoint)</option>
							<option value="snort">Snort Subscriber (Cisco Talos)</option>
						</select>
					</div>
					<div class="form-group">
						<label for="commercial-key">License Key / Oink Code:</label>
						<input
							id="commercial-key"
							type="password"
							bind:value={commercialKey}
							placeholder="Enter your license key"
						/>
					</div>
					<div class="form-actions">
						<button class="btn btn-primary" onclick={handleSaveCommercial} disabled={savingCommercial}>
							{savingCommercial ? 'Saving...' : 'Save'}
						</button>
						<button class="btn btn-ghost" onclick={() => { showCommercialForm = false; }}>
							Cancel
						</button>
					</div>
				</div>
			{:else}
				<button class="btn btn-secondary" onclick={() => { showCommercialForm = true; }}>
					{commercialConfig.configured ? 'Update License' : 'Add Commercial License'}
				</button>
			{/if}
		</section>
	{/if}
</div>

<style>
	.page-container {
		max-width: 960px;
		margin: 0 auto;
		padding: 2rem;
	}

	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		margin-bottom: 1.5rem;
	}

	.page-header h1 {
		font-size: 1.75rem;
		font-weight: 700;
		color: var(--text-primary, #e4e4e7);
		margin: 0;
	}

	.subtitle {
		color: var(--text-secondary, #a1a1aa);
		margin: 0.25rem 0 0;
	}

	.back-link {
		color: var(--accent, #60a5fa);
		text-decoration: none;
		font-size: 0.875rem;
		white-space: nowrap;
	}

	.back-link:hover {
		text-decoration: underline;
	}

	.message {
		padding: 0.75rem 1rem;
		border-radius: 0.5rem;
		margin-bottom: 1rem;
		font-size: 0.875rem;
	}

	.message.success {
		background: rgba(34, 197, 94, 0.15);
		color: #4ade80;
		border: 1px solid rgba(34, 197, 94, 0.3);
	}

	.message.error {
		background: rgba(239, 68, 68, 0.15);
		color: #f87171;
		border: 1px solid rgba(239, 68, 68, 0.3);
	}

	.loading {
		text-align: center;
		padding: 3rem;
		color: var(--text-secondary, #a1a1aa);
	}

	.hero-card {
		background: var(--card-bg, #1e1e2e);
		border: 1px solid var(--border, #2e2e3e);
		border-radius: 0.75rem;
		padding: 1.5rem;
		margin-bottom: 1.5rem;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.hero-stats {
		display: flex;
		gap: 2rem;
	}

	.stat {
		display: flex;
		flex-direction: column;
	}

	.stat-value {
		font-size: 1.5rem;
		font-weight: 700;
		color: var(--text-primary, #e4e4e7);
	}

	.stat-label {
		font-size: 0.75rem;
		color: var(--text-secondary, #a1a1aa);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.card {
		background: var(--card-bg, #1e1e2e);
		border: 1px solid var(--border, #2e2e3e);
		border-radius: 0.75rem;
		padding: 1.5rem;
		margin-bottom: 1.5rem;
	}

	.card h2 {
		font-size: 1.125rem;
		font-weight: 600;
		color: var(--text-primary, #e4e4e7);
		margin: 0 0 0.25rem;
	}

	.section-desc {
		color: var(--text-secondary, #a1a1aa);
		font-size: 0.875rem;
		margin: 0 0 1rem;
	}

	.sources-table {
		width: 100%;
		border-collapse: collapse;
	}

	.sources-table th {
		text-align: left;
		padding: 0.5rem 0.75rem;
		color: var(--text-secondary, #a1a1aa);
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		border-bottom: 1px solid var(--border, #2e2e3e);
	}

	.sources-table td {
		padding: 0.75rem;
		border-bottom: 1px solid var(--border-light, #252535);
		color: var(--text-primary, #e4e4e7);
		font-size: 0.875rem;
	}

	.source-id code {
		background: var(--code-bg, #252535);
		padding: 0.125rem 0.375rem;
		border-radius: 0.25rem;
		font-size: 0.8125rem;
	}

	.source-desc {
		color: var(--text-secondary, #a1a1aa);
	}

	.toggle-btn {
		padding: 0.25rem 0.75rem;
		border-radius: 9999px;
		font-size: 0.75rem;
		font-weight: 600;
		border: 1px solid var(--border, #2e2e3e);
		cursor: pointer;
		background: rgba(239, 68, 68, 0.15);
		color: #f87171;
		transition: all 0.15s;
	}

	.toggle-btn.enabled {
		background: rgba(34, 197, 94, 0.15);
		color: #4ade80;
		border-color: rgba(34, 197, 94, 0.3);
	}

	.toggle-btn:hover:not(:disabled) {
		opacity: 0.8;
	}

	.toggle-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.schedule-row {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.schedule-row label {
		color: var(--text-primary, #e4e4e7);
		font-size: 0.875rem;
	}

	.schedule-row select {
		background: var(--input-bg, #252535);
		color: var(--text-primary, #e4e4e7);
		border: 1px solid var(--border, #2e2e3e);
		border-radius: 0.375rem;
		padding: 0.5rem 0.75rem;
		font-size: 0.875rem;
	}

	.schedule-status {
		font-size: 0.8125rem;
		color: var(--text-secondary, #a1a1aa);
	}

	.custom-rules-editor {
		width: 100%;
		background: var(--input-bg, #0d0d15);
		color: var(--text-primary, #e4e4e7);
		border: 1px solid var(--border, #2e2e3e);
		border-radius: 0.5rem;
		padding: 0.75rem;
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: 0.8125rem;
		line-height: 1.5;
		resize: vertical;
		margin-bottom: 0.75rem;
	}

	.commercial-status {
		display: flex;
		gap: 1.5rem;
		flex-wrap: wrap;
		padding: 0.75rem;
		background: rgba(59, 130, 246, 0.1);
		border: 1px solid rgba(59, 130, 246, 0.2);
		border-radius: 0.5rem;
		margin-bottom: 1rem;
		font-size: 0.875rem;
		color: var(--text-primary, #e4e4e7);
	}

	.commercial-status code {
		background: var(--code-bg, #252535);
		padding: 0.125rem 0.375rem;
		border-radius: 0.25rem;
	}

	.commercial-form {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		margin-top: 0.75rem;
	}

	.form-group {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}

	.form-group label {
		font-size: 0.8125rem;
		color: var(--text-secondary, #a1a1aa);
	}

	.form-group select,
	.form-group input {
		background: var(--input-bg, #252535);
		color: var(--text-primary, #e4e4e7);
		border: 1px solid var(--border, #2e2e3e);
		border-radius: 0.375rem;
		padding: 0.5rem 0.75rem;
		font-size: 0.875rem;
	}

	.form-actions {
		display: flex;
		gap: 0.75rem;
	}

	.btn {
		padding: 0.5rem 1rem;
		border-radius: 0.5rem;
		font-size: 0.875rem;
		font-weight: 500;
		cursor: pointer;
		border: none;
		transition: opacity 0.15s;
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-primary {
		background: var(--accent, #3b82f6);
		color: white;
	}

	.btn-secondary {
		background: var(--card-bg-hover, #252535);
		color: var(--text-primary, #e4e4e7);
		border: 1px solid var(--border, #2e2e3e);
	}

	.btn-ghost {
		background: transparent;
		color: var(--text-secondary, #a1a1aa);
	}

	.btn:hover:not(:disabled) {
		opacity: 0.85;
	}
</style>
