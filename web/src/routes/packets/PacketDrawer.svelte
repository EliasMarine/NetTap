<!--
  PacketDrawer.svelte: one packet, read again in full (NET-188, Main.dc's drawer). A summary
  and the facts, TShark's layers with each field's showname and field name, and the captured
  bytes. A field's bytes are marked only where the daemon proved them (`mark`). The page wraps
  it in {#key row.n}, so each packet starts fresh.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { getPacket, type PacketDetail, type PacketManifest, type PacketNode, type PacketRow } from '$lib/api/packets';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { domainHref, ipHref } from '$lib/stores/lan';
	import { describePacket } from '$lib/utils/packet-describe';
	import { sourceOf } from '$lib/utils/packet-stats';
	import DownloadForm from './DownloadForm.svelte';
	import HexDump from './HexDump.svelte';
	import {
		addressName,
		clockTime,
		dayWords,
		destinationOf,
		dstPortOf,
		field,
		isIp,
		searchProblem,
		sinceFirst,
		srcPortOf,
		type SearchProblem,
	} from './packets-view';

	interface Props {
		manifest: PacketManifest;
		row: PacketRow;
		position: number;
		total: number;
		firstT: string;
		devices: ReadonlyMap<string, string>;
		sites: ReadonlyMap<string, string>;
		onclose: () => void;
		/** Run the search again: the captures changed under it (409). */
		onrerun: () => void;
		/** Every packet of this packet's TCP conversation, over the same window; null outside one */
		conversationHref?: string | null;
	}

	let { manifest, row, position, total, firstT, devices, sites, onclose, onrerun, conversationHref = null }: Props = $props();

	let detail = $state<PacketDetail | null>(null);
	let problem = $state<SearchProblem | null>(null);
	let chosen = $state<PacketNode | null>(null);
	let panel = $state<HTMLElement>();
	let alive = true;
	let attempt = 0;

	async function load() {
		const mine = ++attempt;
		problem = null;
		detail = null;
		try {
			const d = await getPacket(manifest, row.n);
			if (alive && mine === attempt) detail = d;
		} catch (err) {
			if (alive && mine === attempt) problem = searchProblem(err);
		}
	}

	onMount(() => {
		if (panel && getComputedStyle(panel).position === 'static') panel.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
		void load();
		return () => {
			alive = false;
		};
	});

	const src = $derived(sourceOf(row));
	const dst = $derived(destinationOf(row));
	// A device's own name first, then the site its Client Hello named (as addressName does)
	const named = $derived(new Map([...sites, ...devices]));
	const sentence = $derived(describePacket(row, named));
	const site = $derived(field(row, 'tls.handshake.extensions_server_name') ?? field(row, 'http.host') ?? field(row, 'dns.qry.name'));
	const layers = $derived((detail?.layers ?? []).filter((l) => !l.hide && l.name !== 'geninfo'));
	const markLayer = $derived(chosen ? `${chosen.name}` : '');

	const visible = (nodes: PacketNode[]) => nodes.filter((n) => !n.hide);
	const bytesNote = (n: PacketNode) =>
		n.pos !== null && n.size ? ` · bytes ${n.pos} to ${n.pos + n.size - 1}` : '';
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onclose()} />

{#snippet who(address: string | undefined, port: string | undefined)}
	{#if address}
		{@const name = addressName(address, devices, sites)}
		{#if isIp(address)}<a href={$ipHref(address)}>{name}</a>{:else}<span>{name}</span>{/if}
		<span class="mono dim">{name !== address ? address : ''}{port ? ` port ${port}` : ''}</span>
	{:else}<span class="dim">—</span>{/if}
{/snippet}

{#snippet tree(nodes: PacketNode[], markable: boolean)}
	<ul class="fields">
		{#each visible(nodes) as n, i (i)}
			<li>
				{#if n.mark && markable}
					<button class="field-btn" type="button" aria-pressed={chosen === n} onclick={() => (chosen = chosen === n ? null : n)}>
						<span class="show">{n.showname || n.show || n.name}</span>
						<span class="mono dim">{n.name}{bytesNote(n)}</span>
					</button>
				{:else}
					<span class="show">{n.showname || n.show || n.name}</span>
					<span class="mono dim">{n.name}{bytesNote(n)}</span>
				{/if}
				{#if n.children.length}{@render tree(n.children, markable)}{/if}
			</li>
		{/each}
	</ul>
{/snippet}

<aside class="card drawer c-4 packet-drawer" aria-label="Packet {position} of {total}" bind:this={panel}>
	<div class="drawer-head">
		<span class="dim">Packet {position.toLocaleString('en-GB')} of {total.toLocaleString('en-GB')} · frame {row.n.toLocaleString('en-GB')}</span>
		<button class="icon-btn" type="button" aria-label="Close packet details" onclick={onclose}><Icon name="close" /></button>
	</div>
	<div>
		<h2>{sentence ?? row.info}</h2>
		<p class="sig wrap">{row.protocol}{sentence && row.info ? ` · ${row.info}` : ''}</p>
	</div>
	<dl class="facts">
		<dt>Time</dt>
		<dd>{dayWords(row.t)}, <span class="mono">{clockTime(row.t)}</span> · {sinceFirst(row.t, firstT) === 'start' ? 'the first packet' : `${sinceFirst(row.t, firstT)} after the first`}</dd>
		<dt>From</dt>
		<dd>{@render who(src, srcPortOf(row))}</dd>
		<dt>To</dt>
		<dd>{@render who(dst, dstPortOf(row))}</dd>
		<dt>Size</dt>
		<dd>{row.len.toLocaleString('en-GB')} bytes{row.cap_len < row.len ? ` · ${row.cap_len.toLocaleString('en-GB')} saved` : ''}</dd>
		{#if layers.length}
			<dt>Inside</dt>
			<dd class="mono">{layers.map((l) => l.name).join(' › ')}</dd>
		{/if}
		{#if site}
			<dt>Site</dt>
			<dd><a href={domainHref(site)}>{site}</a></dd>
		{/if}
	</dl>

	{#if problem}
		{#if problem.kind === 'changed'}
			<CardState state="error" title="The capture files behind this search have changed" message={problem.message} actionLabel="Run the search again" onaction={onrerun} />
		{:else}
			<CardState state="error" title="Couldn't read this packet" message={problem.message} onaction={() => void load()} />
		{/if}
	{:else if !detail}
		<CardState state="loading" title="Reading packet {row.n} again, up to 45 seconds" />
		<p class="dim" role="status">Reading the window up to this packet again, so TShark sees what came before it…</p>
	{:else}
		<div class="layers" aria-label="What's inside, layer by layer">
			{#each layers as layer, i (i)}
				<details open={i === layers.length - 1}>
					<summary>{layer.showname || layer.name}</summary>
					{#if detail.marking === 'headers' && layer.markable === false}
						<p class="field-help">NetTap couldn't line up this layer's fields with the raw bytes, so they aren't marked here.</p>
					{/if}
					{@render tree(layer.children, detail.marking === 'headers' && layer.markable !== false)}
				</details>
			{/each}
		</div>
		<details open>
			<summary>Raw bytes <span class="dim">{detail.cap_len.toLocaleString('en-GB')} bytes captured</span></summary>
			{#if detail.marking === 'none'}
				<p class="field-help">No bytes are marked for this packet: it was reassembled or changed on the way, so a field's bytes may not sit where its layer says.</p>
			{:else}
				<p class="field-help">Select a field with byte numbers to mark its bytes.</p>
			{/if}
			<HexDump hex={detail.bytes_hex} mark={detail.marking === 'headers' ? (chosen?.mark ?? null) : null} markLabel={markLayer} />
		</details>
	{/if}

	<div class="actions">
		{#if conversationHref}<a class="btn" href={conversationHref}>Show its whole conversation</a>{/if}
		<DownloadForm {manifest} />
		<a class="btn" href="/pcap"><Icon name="pcap" />Open PCAP Search</a>
	</div>
</aside>

<style>
	/* Layout glue: the sticky column scrolls on its own, as AlertDetail does */
	.packet-drawer { align-self: start; max-height: calc(100dvh - var(--sp-8)); overflow-y: auto; }
	.packet-drawer .facts dd { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: var(--sp-1); }
	.dim { color: var(--text-3); font-size: var(--text-xs); }
	details { border-top: 1px solid var(--line); padding-top: var(--sp-2); }
	summary { cursor: pointer; font-size: var(--text-sm); font-weight: 600; color: var(--text-1); overflow-wrap: anywhere; }
	.fields { list-style: none; margin: var(--sp-1) 0 0; padding-left: var(--sp-3); display: flex; flex-direction: column; gap: 2px; }
	.fields li { display: flex; flex-direction: column; font-size: var(--text-xs); color: var(--text-2); min-width: 0; }
	.show { overflow-wrap: anywhere; color: var(--text-1); }
	.field-btn { all: unset; display: flex; flex-direction: column; cursor: pointer; border-radius: var(--r-xs); padding: 1px var(--sp-1); margin-left: calc(var(--sp-1) * -1); }
	.field-btn:hover { background: var(--row-hover); }
	.field-btn[aria-pressed='true'] { background: color-mix(in srgb, var(--accent) 18%, transparent); }
	.field-btn:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
	.layers { display: flex; flex-direction: column; gap: var(--sp-2); }
	@container app (max-width: 1100px) {
		.packet-drawer { max-height: none; overflow: visible; }
	}
</style>
