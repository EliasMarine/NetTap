<script lang="ts">
	/**
	 * SSL Certificate Viewer — Inspect SSL/TLS certificates for any host.
	 *
	 * A form card (host and port), then a certificate card with .facts (subject, issuer,
	 * serial, validity, fingerprint) and the raw output behind a toggle, then cards for
	 * the subject alternative names and the chain. Reads ?host=X on load.
	 */

	import { page } from '$app/stores';
	import { sslCertInspect } from '$api/tools';
	import type { SslCertResult } from '$api/tools';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';

	// ---------------------------------------------------------------------------
	// State
	// ---------------------------------------------------------------------------

	let host = $state('');
	let port = $state(443);
	let result = $state<SslCertResult | null>(null);
	let loading = $state(false);
	let error = $state('');
	let showRaw = $state(false);

	// ---------------------------------------------------------------------------
	// Read URL query params on load
	// ---------------------------------------------------------------------------

	$effect(() => {
		const params = $page.url.searchParams;
		const h = params.get('host');
		if (h) host = h;
	});

	// ---------------------------------------------------------------------------
	// Lookup
	// ---------------------------------------------------------------------------

	async function handleInspect() {
		const trimmed = host.trim();
		if (!trimmed) return;

		loading = true;
		error = '';
		result = null;
		showRaw = false;

		try {
			result = await sslCertInspect(trimmed, port);
			if (result.error) error = result.error;
		} catch (e) {
			error = e instanceof Error ? e.message : 'SSL inspection failed';
		} finally {
			loading = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleInspect();
	}

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	// OLD CODE START — the badge classes became system chip tones; the thresholds and labels are unchanged
	// function validityBadge(notAfter: string): { label: string; cls: string } {
	// 	if (!notAfter) return { label: 'Unknown', cls: 'badge-muted' };
	// 	const expiry = new Date(notAfter);
	// 	const now = new Date();
	// 	const daysLeft = Math.floor((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
	// 	if (daysLeft < 0) return { label: `Expired ${Math.abs(daysLeft)}d ago`, cls: 'badge-danger' };
	// 	if (daysLeft <= 30) return { label: `Expires in ${daysLeft}d`, cls: 'badge-warning' };
	// 	return { label: `Valid (${daysLeft}d remaining)`, cls: 'badge-success' };
	// }
	// OLD CODE END
	// OLD CODE START — 2026-11-06 (S1): "Valid" came from the expiry date alone (an untrusted or
	// wrong-name certificate read green), and a date it couldn't parse read "Valid (NaNd remaining)"
	// function validityBadge(notAfter: string): { label: string; cls: string } {
	// 	if (!notAfter) return { label: 'Unknown', cls: '' };
	// 	const expiry = new Date(notAfter);
	// 	const now = new Date();
	// 	const daysLeft = Math.floor((expiry.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
	// 	if (daysLeft < 0) return { label: `Expired ${Math.abs(daysLeft)}d ago`, cls: 'is-bad' };
	// 	if (daysLeft <= 30) return { label: `Expires in ${daysLeft}d`, cls: 'is-warn' };
	// 	return { label: `Valid (${daysLeft}d remaining)`, cls: 'is-ok' };
	// }
	// OLD CODE END
	type Chip = { label: string; cls: string };
	const DAY_MS = 86_400_000;
	const days = (n: number) => `${n} day${n === 1 ? '' : 's'}`;

	/** openssl's own verdict on the chain and the name, never the expiry date. */
	function trustChip(r: SslCertResult): Chip {
		if (r.trusted === true) return { label: 'Trusted', cls: 'is-ok' };
		if (r.trusted === false) return { label: `Not trusted: ${r.verify_errors.join('; ') || 'verification failed'}`, cls: 'is-bad' };
		return { label: 'Trust not checked', cls: '' };
	}

	/** Time to expiry; null when the date can't be read. */
	function expiryChip(notAfter: string): Chip | null {
		const ms = notAfter ? new Date(notAfter).getTime() : NaN;
		if (!Number.isFinite(ms)) return null;
		const left = Math.floor((ms - Date.now()) / DAY_MS);
		if (left < 0) return { label: `Expired ${days(-left)} ago`, cls: 'is-bad' };
		return { label: `Expires in ${days(left)}`, cls: left <= 30 ? 'is-warn' : '' };
	}

	function formatDate(d: string): string {
		// OLD CODE START — 2026-11-06 (S1): an unparseable date printed "Invalid Date"
		// if (!d) return '--';
		// OLD CODE END
		if (!d || !Number.isFinite(new Date(d).getTime())) return '—';
		try {
			return new Date(d).toLocaleDateString('en-US', {
				year: 'numeric',
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
				timeZoneName: 'short',
			});
		} catch {
			return d;
		}
	}

	// OLD CODE START — 2026-11-06 (S1): one chip that judged validity by the date alone
	// let validity = $derived(result ? validityBadge(result.not_after) : null);
	// OLD CODE END
	let trust = $derived(result ? trustChip(result) : null);
	let expiry = $derived(result ? expiryChip(result.not_after) : null);
</script>

<svelte:head>
	<title>SSL certificate viewer | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">SSL certificate viewer</h1>
		<p class="page-sub">Inspect the TLS certificate a host presents, check its validity and read its chain.</p>
	</div>
</div>

<div class="grid">
	<Card title="Inspect a host" sub="Host name or IP address, and its TLS port" class="c-4">
		<div class="field form-group">
			<label class="label" for="ssl-host">Host</label>
			<input id="ssl-host" type="text" class="input mono" placeholder="example.com" bind:value={host} onkeydown={handleKeydown} />
		</div>
		<div class="field">
			<label class="label" for="ssl-port">Port</label>
			<input id="ssl-port" type="number" class="input mono" bind:value={port} min="1" max="65535" />
		</div>
		<div class="form-actions">
			<button class="btn primary" type="button" onclick={handleInspect} disabled={loading || !host.trim()}>
				<Icon name="certs" />{loading ? 'Inspecting…' : 'Inspect'}
			</button>
		</div>
	</Card>

	<Card title="Certificate" sub="The leaf certificate the host presented" class="c-8">
		{#snippet actions()}
			<!-- OLD CODE START — 2026-11-06 (S1): one validity chip from the expiry date
			{#if validity && result && !result.error && !loading && !error}
				<span class={['chip', validity.cls]}>{validity.label}</span>
			{/if}
			OLD CODE END -->
			{#if result && !result.error && !loading && !error}
				{#if trust}<span class={['chip', trust.cls]}>{trust.label}</span>{/if}
				<span class={['chip', expiry?.cls]}>{expiry?.label ?? 'Expiry —'}</span>
			{/if}
		{/snippet}
		{#if loading}
			<CardState state="loading" title="Inspecting the certificate" />
		{:else if error}
			<CardState state="error" title="Inspection failed" message={error} />
		{:else if result && !result.error}
			<dl class="facts">
				<dt>Host</dt>
				<dd class="mono">{result.host}:{result.port}</dd>
				<dt>Subject CN</dt>
				<dd class="mono">{result.subject?.CN || result.subject?.commonName || '—'}</dd>
				<dt>Issuer</dt>
				<dd>{result.issuer?.CN || result.issuer?.O || result.issuer?.commonName || '—'}</dd>
				<dt>Name check</dt>
				<dd>{result.name_match === true ? `Covers ${result.host}` : result.name_match === false ? `Doesn't cover ${result.host}` : '—'}</dd>
				<dt>Serial number</dt>
				<dd class="mono">{result.serial || '—'}</dd>
				<dt>Not before</dt>
				<dd>{formatDate(result.not_before)}</dd>
				<dt>Not after</dt>
				<dd>{formatDate(result.not_after)}</dd>
				<dt>SHA-256 fingerprint</dt>
				<dd class="mono">{result.fingerprint_sha256 || '—'}</dd>
			</dl>
			{#if result.raw}
				<div class="actions raw-toggle">
					<button class="btn" type="button" aria-expanded={showRaw} aria-controls="ssl-raw" onclick={() => (showRaw = !showRaw)}>
						{showRaw ? 'Hide' : 'Show'} raw certificate output
					</button>
				</div>
				{#if showRaw}
					<pre class="raw mono" id="ssl-raw">{result.raw}</pre>
				{/if}
			{/if}
		{:else}
			<CardState state="empty" icon="certs" title="Enter a host" message="Type a host name and choose Inspect to read its certificate." />
		{/if}
	</Card>

	{#if !loading && !error && result && !result.error}
		{#if result.san && result.san.length > 0}
			<Card title="Subject alternative names" sub="{result.san.length} names this certificate covers" class="c-6">
				<ul class="chips names">
					{#each result.san as name, i (i)}
						<li class="chip mono">{name}</li>
					{/each}
				</ul>
			</Card>
		{/if}
		{#if result.chain && result.chain.length > 0}
			<Card title="Certificate chain" sub="{result.chain.length} certificates, leaf first" class="c-6">
				<ol class="chain">
					{#each result.chain as cert, i (i)}
						<li><span class="tile num">{i + 1}</span><span class="mono">{cert}</span></li>
					{/each}
				</ol>
			</Card>
		{/if}
	{/if}
</div>

<style>
	.raw-toggle { margin-top: var(--sp-4); }
	/* Layout glue: the raw output as an inset, scrollable block */
	.raw {
		margin: var(--sp-3) 0 0; padding: var(--sp-3) var(--sp-4); max-height: 420px; overflow: auto;
		white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--text-xs); color: var(--text-2);
		background: var(--surface-1); border: 1px solid var(--line); border-radius: var(--r-md);
	}
	.names { list-style: none; margin: 0; padding: 0; }
	/* Layout glue: each chain step numbered in a small tile */
	.chain { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--sp-2); font-size: var(--text-sm); }
	.chain li { display: flex; align-items: center; gap: var(--sp-3); min-width: 0; overflow-wrap: anywhere; }
	.chain .tile { width: 28px; height: 28px; font-size: var(--text-xs); font-weight: 700; }
</style>
