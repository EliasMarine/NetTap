<script lang="ts">
	/**
	 * IPv6 toolkit (NET-218): explains any IPv6 address in plain English, in the browser.
	 * The maths is $lib/utils/ipv6.ts. The maker of a candidate MAC comes from the daemon's
	 * MAC lookup, debounced and guarded so a late reply never overwrites a newer one.
	 */
	import { page } from '$app/stores';
	import { replaceState } from '$app/navigation';
	import { macLookup } from '$api/tools';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import DataTable, { type Column } from '$lib/components/ui/DataTable.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { ipHref } from '$lib/stores/lan';
	import { inspect, slaac, TYPES, type InterfaceInfo } from '$lib/utils/ipv6';
	import CopyButton from './CopyButton.svelte';

	const LOOKUP_DELAY_MS = 400;

	const EXAMPLES: [string, string][] = [
		['Link-local from a MAC', 'fe80::a00:27ff:fe4e:66a1%eth0'],
		['Home ISP block', '2001:db8:abcd:1200::/56'],
		['Private (ULA)', 'fd12:3456:789a:1::1b'],
		['IPv4-mapped', '::ffff:192.0.2.10'],
		['mDNS multicast', 'ff02::fb'],
		['Teredo tunnel', '2001:0:4136:e378:8000:63bf:3fff:fdd2'],
	];

	const RANGE_EXAMPLES: Record<string, string> = {
		global: '2606:4700:4700::1111', ula: 'fd00::1', linklocal: 'fe80::1%eth0', multicast: 'ff02::1', loopback: '::1',
		mapped: '::ffff:192.0.2.1', nat64: '64:ff9b::c000:201', documentation: '2001:db8::1', '6to4': '2002:c000:201::1',
		teredo: '2001:0:4136:e378:8000:63bf:3fff:fdd2',
	};

	interface RangeRow { key: string; range: string; label: string; example: string }
	const rangeRows: RangeRow[] = TYPES.filter((t) => t.key in RANGE_EXAMPLES).map((t) => ({
		key: t.key, range: `${t.net}/${t.len}`, label: t.label, example: RANGE_EXAMPLES[t.key],
	}));

	/** How the last 64 bits look: a pattern, never proof of how the device made them (RFC 7136) */
	const IFACE_TEXT: Record<InterfaceInfo['kind'], { how: string; why: string; chip?: [string, string] }> = {
		eui64: { how: 'Matches the EUI-64 pattern', why: 'It was probably built from the MAC address below, which names the hardware and lets the device be followed from network to network.', chip: ['is-caution', 'May reveal the MAC'] },
		random: { how: 'No MAC pattern', why: 'Likely a privacy or stable private address. How it was made can\'t be proven from the address alone.', chip: ['is-ok', 'Likely private'] },
		low: { how: 'A small number', why: 'Looks set by hand or by DHCPv6, typical of routers and servers.' },
		anycast: { how: 'All zeros', why: 'The subnet-router anycast address: it reaches any router on this network.' },
	};

	let address = $state($page.url.searchParams.get('address') ?? '');
	let result = $derived(inspect(address));
	let shown = $derived(result.ok ? result.compressed + (result.zone ? `%${result.zone}` : '') + (result.typedPrefix !== null ? `/${result.typedPrefix}` : '') : '');

	/** Keep the address in the URL so a result can be shared; shallow, so nothing reloads */
	function syncUrl() {
		const url = new URL(window.location.href);
		const q = address.trim();
		if (q) url.searchParams.set('address', q);
		else url.searchParams.delete('address');
		replaceState(url, {});
	}

	let input = $state<HTMLInputElement>();
	function load(value: string) {
		address = value;
		syncUrl();
		input?.focus();
	}

	// ---------------------------------------------------------------- Maker of the candidate MAC

	type Maker = { state: 'loading' | 'local' } | { state: 'done'; vendor: string | null } | { state: 'error'; message: string };
	let candidateMac = $derived(result.ok && result.iface?.kind === 'eui64' ? (result.iface.mac ?? null) : null);
	let candidateLocal = $derived(result.ok && result.iface?.localMac === true);
	let maker = $state<Maker | null>(null);
	/** Bumped on every candidate change and on teardown: only the newest lookup may write */
	let lookupGen = 0;

	$effect(() => {
		const mac = candidateMac;
		const local = candidateLocal;
		const gen = ++lookupGen;
		if (!mac) {
			maker = null;
			return;
		}
		if (local) {
			maker = { state: 'local' };
			return;
		}
		maker = { state: 'loading' };
		const timer = setTimeout(async () => {
			try {
				const r = await macLookup(mac);
				if (gen === lookupGen) maker = { state: 'done', vendor: r.found && r.vendor ? r.vendor : null };
			} catch (e) {
				if (gen === lookupGen) maker = { state: 'error', message: e instanceof Error ? e.message : 'the request failed' };
			}
		}, LOOKUP_DELAY_MS);
		return () => {
			clearTimeout(timer);
			lookupGen++;
		};
	});

	// ---------------------------------------------------------------- MAC to address

	let mac = $state('');
	let macPrefix = $state('');
	let built = $derived(mac.trim() ? slaac(mac, macPrefix) : null);

	const rangeColumns: Column<RangeRow>[] = [
		{ key: 'range', label: 'Range', class: 'mono' },
		{ key: 'label', label: 'What it is' },
		{ key: 'example', label: 'Example', cell: exampleCell },
	];
</script>

{#snippet exampleCell(row: RangeRow)}
	<button class="ex" type="button" onclick={() => load(row.example)} aria-label="Explain {row.example}">{row.example}</button>
{/snippet}

{#snippet copyable(value: string, what: string)}
	<span class="mono">{value}</span><CopyButton {value} {what} />
{/snippet}

<svelte:head>
	<title>IPv6 toolkit | NetTap</title>
</svelte:head>

<div class="page-head">
	<div>
		<a class="back" href="/tools"><Icon name="back" />Tools</a>
		<h1 class="page-title">IPv6 toolkit</h1>
		<p class="page-sub">Read any IPv6 address in plain English: what kind it is, every way to write it, its block and the device behind it. Runs in your browser.</p>
	</div>
</div>

<div class="grid">
	<Card title="Address" sub="One IPv6 address, with or without a /prefix or %zone" class="c-4">
		<div class="field">
			<label class="label" for="v6-input">IPv6 address</label>
			<input id="v6-input" class="input mono" type="text" spellcheck="false" autocomplete="off" placeholder="2001:db8::1 or fe80::1%eth0" aria-describedby="v6-help" bind:this={input} bind:value={address} oninput={syncUrl} />
			<span class="field-help" id="v6-help">Paste it from a log, a device page or a URL such as [2001:db8::1]:443.</span>
		</div>
		<h3 class="eyebrow ex-label">Try an example</h3>
		<div class="examples">
			{#each EXAMPLES as [label, value] (value)}
				<button class="btn" type="button" onclick={() => load(value)}>{label}</button>
			{/each}
		</div>
	</Card>

	<Card title="What this address is" sub="Type, reach and every way to write it" class="c-8">
		{#snippet actions()}
			{#if result.ok && result.type.key !== 'multicast'}
				<a class="btn" href={$ipHref(result.compressed)}><Icon name="search" />Open address page</a>
			{/if}
		{/snippet}
		{#if result.ok}
			<div class="verdict">
				<span class={['chip', result.type.caution && 'is-caution']}>{#if result.type.caution}<Icon name="warn" />{/if}{result.type.label}</span>
				<p class="verdict-addr mono">{shown}</p>
				<p class="verdict-text">{result.type.text}{#if result.ulaNote}{' '}{result.ulaNote}{/if}</p>
			</div>
			<dl class="facts">
				<dt>Short form</dt><dd>{@render copyable(result.compressed, 'short form')}</dd>
				<dt>Full form</dt><dd>{@render copyable(result.expanded, 'full form')}</dd>
				<dt>Reach</dt><dd>{result.reach}</dd>
				{#if result.group}<dt>Group</dt><dd>{result.group}</dd>{/if}
				{#if result.zone}
					<dt>Zone</dt><dd><span class="mono">{result.zone}</span><span class="note">The interface this address is on</span></dd>
				{:else if result.zoneMissing}
					<dt>Zone</dt><dd>None given<span class="note">To ping or connect, add the interface, such as %eth0: every interface has its own fe80::/64.</span></dd>
				{/if}
				{#each result.embedded as e (e.label)}
					<dt>{e.label}</dt><dd>{@render copyable(e.value, e.label)}</dd>
				{/each}
				{#if result.solicited}
					<dt>Neighbour discovery group</dt><dd>{@render copyable(result.solicited, 'neighbour discovery group')}<span class="note">Where other devices ask "who has this address?"</span></dd>
				{/if}
				<dt>Reverse DNS name</dt><dd class="rev">{@render copyable(result.reverse, 'reverse DNS name')}</dd>
			</dl>
		{:else if result.error}
			<p class="notice is-error" role="alert">
				<Icon name="warn" /><span>{result.error}{#if result.hint === 'ipv4'}{' '}<a href="/tools/subnet-calc">Open the Subnet calculator</a>{/if}</span>
			</p>
		{:else}
			<CardState state="empty" icon="dns" title="Enter an IPv6 address" message="Paste or type one, or try an example. Nothing leaves your browser." />
		{/if}
	</Card>
</div>

{#if result.ok && (result.block || result.iface || result.isNetwork)}
	<div class="grid">
		{#if result.block}
			{@const b = result.block}
			<Card title="Block" sub={b.assumed ? `/${b.len} assumed: no prefix was typed, and /${b.len} is the usual size here` : `/${b.len}, as typed`} class="c-6">
				<dl class="facts">
					<dt>Block</dt><dd>{@render copyable(b.block, 'block')}</dd>
					<dt>First address</dt><dd>{@render copyable(b.first, 'first address')}</dd>
					<dt>Last address</dt><dd>{@render copyable(b.last, 'last address')}</dd>
					{#if b.subnets64}<dt>Networks of /64</dt><dd class="num">{b.subnets64}</dd>{/if}
					<dt>Addresses</dt><dd class="num">{#if b.addresses}{b.addresses}{:else}2<sup>{b.hostBits}</sup>{/if}</dd>
				</dl>
				{#if b.note}<p class="size-note">{b.note}</p>{/if}
			</Card>
		{/if}
		{#if result.iface}
			{@const f = result.iface}
			{@const t = IFACE_TEXT[f.kind]}
			<Card title="Device part" sub="The last 64 bits, which name a device on its network" class="c-6">
				{#snippet actions()}
					{#if f.mac}<a class="btn" href="/tools/mac-lookup"><Icon name="devices" />MAC vendor lookup</a>{/if}
				{/snippet}
				<dl class="facts">
					<dt>Interface ID</dt><dd>{@render copyable(f.id, 'interface ID')}</dd>
					<dt>How it was made</dt>
					<dd>{t.how}{#if t.chip}{' '}<span class="chip {t.chip[0]}">{t.chip[1]}</span>{/if}<span class="note">{t.why}</span></dd>
					{#if f.mac}
						<dt>Candidate MAC</dt><dd>{@render copyable(f.mac, 'candidate MAC')}</dd>
						<dt>Maker of that MAC</dt>
						<dd>
							{#if maker?.state === 'done'}{maker.vendor ?? 'Maker unknown'}
							{:else if maker?.state === 'error'}<span class="lookup-error">Couldn't look up the maker: {maker.message}</span>
							{:else if maker?.state === 'local'}None<span class="note">A locally administered MAC has no maker.</span>
							{:else}Looking up…{/if}
						</dd>
					{/if}
				</dl>
			</Card>
		{:else if result.isNetwork}
			<Card title="Device part" sub="The last 64 bits, which name a device on its network" class="c-6">
				<CardState state="empty" icon="devices" title="No device part" message="Read as a network, because every bit after /{result.typedPrefix} is zero. Type an address inside it to see a device part." />
			</Card>
		{/if}
	</div>
{/if}

<div class="grid">
	<Card title="MAC to IPv6 address" sub="The address a device builds from its MAC with SLAAC (EUI-64)" class="c-5">
		<div class="form-row">
			<div class="field">
				<label class="label" for="mac-input">MAC address</label>
				<input id="mac-input" class="input mono" type="text" spellcheck="false" autocomplete="off" placeholder="08:00:27:4e:66:a1" bind:value={mac} />
			</div>
			<div class="field">
				<label class="label" for="mac-prefix">Network prefix (optional)</label>
				<input id="mac-prefix" class="input mono" type="text" spellcheck="false" autocomplete="off" placeholder="2001:db8:1:2::/64" aria-describedby="mac-prefix-help" bind:value={macPrefix} />
				<span class="field-help" id="mac-prefix-help">Leave it empty for the link-local address. Give your /64 to see the public address the device will pick.</span>
			</div>
		</div>
		{#if built?.ok}
			<dl class="facts built">
				<dt>IPv6 address</dt><dd>{@render copyable(built.address, 'IPv6 address')}</dd>
				<dt>Interface ID</dt><dd>{@render copyable(built.id, 'built interface ID')}</dd>
			</dl>
			<div class="form-actions built-actions">
				<button class="btn" type="button" onclick={() => built?.ok && load(built.address)}><Icon name="search" />Explain this address</button>
			</div>
		{:else if built}
			<p class="notice is-error built" role="alert"><Icon name="warn" /><span>{built.error}</span></p>
		{/if}
	</Card>

	<Card title="Address ranges" sub="The ranges you will meet on a home network · choose an example to explain it" class="c-7">
		<details class="ranges">
			<summary>Show the {rangeRows.length} ranges</summary>
			<DataTable columns={rangeColumns} rows={rangeRows} ariaLabel="IPv6 address ranges" rowKey={(r) => r.key} />
		</details>
	</Card>
</div>

<style>
	/* Layout glue the system lacks; colours and sizes are tokens */
	.ex-label { margin-top: var(--sp-5); }
	.examples { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-top: var(--sp-3); }
	.examples .btn { min-height: 30px; padding: 0 var(--sp-3); font-size: var(--text-xs); }
	.verdict { display: flex; flex-direction: column; align-items: flex-start; gap: var(--sp-2); padding-bottom: var(--sp-4); }
	.verdict-addr { font-size: var(--text-lg); color: var(--text-1); overflow-wrap: anywhere; }
	.verdict-text { color: var(--text-2); font-size: var(--text-sm); max-width: 62ch; }
	.facts .note { display: block; color: var(--text-3); font-size: var(--text-xs); }
	.facts .rev { font-size: var(--text-xs); }
	.lookup-error { color: var(--sev-critical); }
	.size-note { margin-top: var(--sp-3); font-size: var(--text-sm); color: var(--text-2); }
	.form-row { display: flex; flex-direction: column; gap: var(--sp-3); }
	.built { margin-top: var(--sp-4); }
	.built-actions { margin-top: var(--sp-4); }
	.ranges summary { cursor: pointer; color: var(--text-2); font-size: var(--text-sm); font-weight: 600; }
	.ranges summary:hover { color: var(--text-1); }
	.ranges[open] summary { margin-bottom: var(--sp-3); }
	.ex { all: unset; cursor: pointer; font-family: var(--font-mono); font-size: var(--text-xs); color: var(--accent); }
	.ex:hover { text-decoration: underline; }
	.ex:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
</style>
