<!--
  AlertDetail.svelte: the sticky alert drawer column for /alerts and /alerts/[category]
  (nettap-design-system/components/AlertDrawer). Fixed order: pill and close, title and the
  wrapped signature, explanation, What to do, facts, actions. Below the actions, collapsed:
  Related events and Raw JSON from the restyled AlertDrawerContent, and the copyable metadata.
  It replaces the fixed DetailDrawer overlay on these pages, which can't sit in a grid column.
  Escape closes it. The page wraps it in {#key alert._id} so each alert starts fresh.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import type { Alert } from '$api/alerts';
	import Icon from '$lib/components/ui/Icon.svelte';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import IPAddress from '$components/IPAddress.svelte';
	import { ipHref, isLan } from '$lib/stores/lan';
	import DrawerSection from '$components/drawer/DrawerSection.svelte';
	import KVRow from '$components/drawer/KVRow.svelte';
	import AlertDrawerContent from '$components/drawer/content/AlertDrawerContent.svelte';
	// OLD CODE: import { alertAdvice, alertExplanation, alertLevel, alertTitle, logExplorerHref } from './alert-view'; (slice 2b-2)
	import { alertAdvice, alertExplanation, alertLevel, alertTitle, linkedSuricataCategory, logExplorerHref } from './alert-view';
	// OLD CODE: import { alertsHrefForSignature } from '$lib/utils/drilldown'; (slice 2b-2)
	import { alertsHrefForSignature, suricataCategoryHref } from '$lib/utils/drilldown';

	interface Props {
		alert: Alert;
		onclose: () => void;
		/** Each action throws with the reason when it was not applied. */
		onacknowledge: () => Promise<void>;
		onsuppress: () => Promise<void>;
		onfalsepositive: () => Promise<void>;
	}

	let { alert, onclose, onacknowledge, onsuppress, onfalsepositive }: Props = $props();

	let error = $state('');
	let busy = $state(false);
	let panel = $state<HTMLElement>();

	// Under 1100 px the column sits below the list (position: static), out of sight: bring it in
	onMount(() => {
		if (panel && getComputedStyle(panel).position === 'static') panel.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
	});

	const explanation = $derived(alertExplanation(alert));
	const hasSignatureId = $derived(Boolean(alert.alert?.signature_id));
	const suricataCategory = $derived(linkedSuricataCategory(alert));

	async function act(action: () => Promise<void>) {
		error = '';
		busy = true;
		try {
			await action();
		} catch (err) {
			error = err instanceof Error ? err.message : 'Action failed';
		} finally {
			busy = false;
		}
	}

	function formatTimestamp(ts: string | undefined): string {
		if (!ts) return '—';
		const d = new Date(ts);
		return Number.isFinite(d.getTime())
			? d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' })
			: ts;
	}

	// OLD CODE START — NET-160: the device page for every address, internet ones included
	// const device = (ip: string) => `/devices/${encodeURIComponent(ip)}`;
	// OLD CODE END
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onclose()} />

<aside class="card drawer c-4 alert-detail" aria-label="Alert details" bind:this={panel}>
	<div class="drawer-head">
		<SeverityPill level={alertLevel(alert.alert?.severity)} />
		<button class="icon-btn" type="button" aria-label="Close details" onclick={onclose}><Icon name="close" /></button>
	</div>
	<div>
		<h2>{alertTitle(alert)}</h2>
		<!-- OLD CODE: <p class="sig wrap">{alert.alert?.signature || 'Unknown signature'}</p> (slice 2a: not a link) -->
		<!-- OLD CODE: <p class="sig wrap">{#if alert.alert?.signature}<a href={alertsHrefForSignature(alert.alert.signature)}>{alert.alert.signature}</a>{:else}Unknown signature{/if}</p> (slice 2b-1: the list's filter matches rule.name, not the shown signature) -->
		<p class="sig wrap">{#if alert.rule?.name}<a href={alertsHrefForSignature(alert.rule.name)}>{alert.alert?.signature || alert.rule.name}</a>{:else}{alert.alert?.signature || 'Unknown signature'}{/if}</p>
	</div>
	{#if explanation}<p class="drawer-plain">{explanation}</p>{/if}
	<div class="todo"><b>What to do</b>{alertAdvice(alert)}</div>
	<dl class="facts">
		<dt>Source</dt>
		<dd>
			{#if alert.src_ip}<IPAddress ip={alert.src_ip} />{#if alert.src_port}<span class="mono dim">:{alert.src_port}</span>{/if}{:else}<span class="dim">—</span>{/if}
		</dd>
		<dt>Destination</dt>
		<dd>
			{#if alert.dest_ip}<IPAddress ip={alert.dest_ip} />{#if alert.dest_port}<span class="mono dim">:{alert.dest_port}</span>{/if}{:else}<span class="dim">—</span>{/if}
		</dd>
		<dt>Protocol</dt>
		<dd class="mono">{alert.proto ? alert.proto.toUpperCase() : '—'}</dd>
		<dt>Category</dt>
		<!-- OLD CODE: <dd>{alert.alert?.category || '—'}</dd> (slice 2b-2: its page, over the default 24 hours, as the drawer's other links) -->
		<dd>{#if suricataCategory}<a href={suricataCategoryHref(suricataCategory)}>{suricataCategory}</a>{:else}{alert.alert?.category || '—'}{/if}</dd>
		<dt>Seen</dt>
		<dd class="num">{formatTimestamp(alert.timestamp)}</dd>
		<dt>Signature ID</dt>
		<dd class="mono">{alert.alert?.signature_id ?? '—'}</dd>
		<dt>Status</dt>
		<dd>{alert.acknowledged ? `Acknowledged ${formatTimestamp(alert.acknowledged_at)}` : 'Not acknowledged'}</dd>
	</dl>
	{#if error}
		<p class="notice is-error" role="alert"><Icon name="warn" />Not applied: {error}</p>
	{/if}
	<div class="actions">
		{#if alert.src_ip}
			<a class="btn primary" href="/connections?ip={encodeURIComponent(alert.src_ip)}"><Icon name="connections" />View connections</a>
		{/if}
		{#if !alert.acknowledged}
			<button class="btn" type="button" disabled={busy} onclick={() => act(onacknowledge)}><Icon name="check" />Acknowledge</button>
		{/if}
		{#if hasSignatureId}
			<button class="btn" type="button" title="Suppress this signature" disabled={busy} onclick={() => act(onsuppress)}>Suppress</button>
			<button class="btn" type="button" title="Mark as false positive" disabled={busy} onclick={() => act(onfalsepositive)}>False positive</button>
		{/if}
		<!-- OLD CODE START — NET-160
		{#if alert.src_ip}<a class="btn" href={device(alert.src_ip)}>View source device</a>{/if}
		{#if alert.dest_ip}<a class="btn" href={device(alert.dest_ip)}>View destination device</a>{/if}
		OLD CODE END -->
		{#if alert.src_ip}<a class="btn" href={$ipHref(alert.src_ip)}>{$isLan(alert.src_ip) === true ? 'Open source device' : 'Open source address'}</a>{/if}
		{#if alert.dest_ip}<a class="btn" href={$ipHref(alert.dest_ip)}>{$isLan(alert.dest_ip) === true ? 'Open destination device' : 'Open destination address'}</a>{/if}
		<a class="btn" href={logExplorerHref(alert)}><Icon name="logs" />View in Log Explorer</a>
	</div>
	<div class="more">
		<DrawerSection title="Related events" defaultExpanded={false}>
			<AlertDrawerContent {alert} activeTab="related" />
		</DrawerSection>
		<DrawerSection title="Raw JSON" defaultExpanded={false}>
			<AlertDrawerContent {alert} activeTab="raw" />
		</DrawerSection>
		<DrawerSection title="Metadata" defaultExpanded={false}>
			<KVRow label="Alert ID" value={alert._id} mono copyable />
			<KVRow label="Index" value={alert._index} mono />
		</DrawerSection>
	</div>
</aside>

<style>
	/* Layout glue: the sticky column scrolls on its own when taller than the viewport */
	.alert-detail { align-self: start; max-height: calc(100dvh - var(--sp-8)); overflow-y: auto; }
	.alert-detail .facts dd { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 2px; }
	.more { border-top: 1px solid var(--line); }
	@container app (max-width: 1100px) {
		.alert-detail { max-height: none; overflow: visible; }
	}
</style>
