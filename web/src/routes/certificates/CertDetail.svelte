<script lang="ts">
	/**
	 * The Certificates drawer (NET-154), for a finding or a site: what it means, what to do, and
	 * every certificate's stored facts. Devices, servers and sites link on to where they can be
	 * investigated further. Certificate-wide figures are labelled as such, never as the site's.
	 */
	import { onMount } from 'svelte';
	import type { CertDetail, CertFinding, CertSite } from '$lib/api/certificates';
	import Icon from '$lib/components/ui/Icon.svelte';
	import { domainHref, ipHref, isLan } from '$lib/stores/lan';
	import SeverityPill from '$lib/components/ui/SeverityPill.svelte';
	import {
		deviceName,
		findingAdvice,
		findingEvidence,
		findingExplanation,
		findingTitle,
		formatDay,
		formatWhen,
		siteName,
		statusList,
		type Names,
		type StatusChip,
	} from './cert-view';

	interface Props {
		finding?: CertFinding;
		site?: CertSite;
		/** The site's status, shown when the drawer is for a site. */
		status?: StatusChip;
		details: Readonly<Record<string, CertDetail>>;
		names: Names;
		onclose: () => void;
	}

	let { finding, site, status, details, names, onclose }: Props = $props();

	let panel = $state<HTMLElement>();

	// Under 1100 px the column sits below the list (position: static), out of sight: bring it in
	onMount(() => {
		if (panel && getComputedStyle(panel).position === 'static') panel.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
	});

	const fmt = (n: number): string => n.toLocaleString('en-GB');
	const holder = $derived(finding ?? site);
	const servers = $derived(finding ? finding.servers : (site?.servers ?? []));
	const fingerprints = $derived(finding ? [finding.fingerprint] : (site?.certificates ?? []));
	const certCount = $derived(finding ? 1 : (site?.certificates_total ?? 0));
	const name = $derived(finding ? siteName(finding.site, finding.server) : siteName(site?.name, site?.server));
	const hostName = $derived(finding ? finding.site : site?.name);
	const server = $derived(finding ? finding.server : (site?.servers[0] ?? site?.server ?? null));

	const device = (ip: string): string => `/devices/${encodeURIComponent(ip)}`;
	/**
	 * NET-160: where the site drills down, from its structured identity: a real SNI name to its
	 * domain page, a site with no name to its server's address page; anything else stays text.
	 */
	const siteLink = $derived.by((): { href: string; label: string } | null => {
		if (hostName) return { href: domainHref(hostName), label: 'Open domain page' };
		const noName = finding ? finding.server : (site?.server ?? null);
		if (!noName) return null;
		return { href: $ipHref(noName), label: $isLan(noName) === true ? 'Open device page' : 'Open address page' };
	});
	/** A certificate's site id: "no-sni:<ip>" for a server reached with no name, else the name. */
	const certSiteHref = (id: string): string => (id.startsWith('no-sni:') ? $ipHref(id.slice(7)) : domainHref(id));
	const connections = (ip: string): string => `/connections?ip=${encodeURIComponent(ip)}`;

	function versions(cert: CertDetail): string {
		const entries = Object.entries(cert.tls_versions).sort((a, b) => b[1] - a[1]);
		return entries.length ? entries.map(([v, n]) => `${v} (${fmt(n)})`).join('; ') : '—';
	}

	function key(cert: CertDetail): string {
		const parts = [cert.key_type && `${cert.key_type.toUpperCase()}${cert.key_length ? ` ${cert.key_length}` : ''}`, cert.sig_alg].filter(Boolean);
		return parts.length ? parts.join(' · ') : '—';
	}
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onclose()} />

<aside class="card drawer c-4 cert-detail" aria-label="Certificate details" bind:this={panel}>
	<div class="drawer-head">
		{#if finding}
			<SeverityPill level={finding.severity} />
		{:else if status}
			<span class="chip {status.tone}">{status.label}</span>
		{/if}
		<button class="icon-btn" type="button" aria-label="Close details" onclick={onclose}><Icon name="close" /></button>
	</div>

	{#if finding}
		<div>
			<h2>{findingTitle(finding, names)}</h2>
			<p class="sig wrap">{findingEvidence(finding)}</p>
		</div>
		<p class="drawer-plain">{findingExplanation(finding, details[finding.fingerprint], names)}</p>
		<div class="todo"><b>What to do</b>{findingAdvice(finding)}</div>
	{:else if site}
		<div>
			<h2 class="mono wrap">{name}</h2>
			<p class="sig wrap">
				{fmt(site.sessions)} sessions · {formatWhen(site.first_seen)} to {formatWhen(site.last_seen)} · {statusList(site.statuses)}
			</p>
		</div>
		{#if site.authorities.length > 1}
			<p class="drawer-plain">
				This site's certificates came from {site.authorities.length} authorities: {site.authorities.join(', ')}. Big sites switch
				between well-known authorities often; a switch is listed under Needs a look only when a certificate couldn't be verified.
			</p>
		{/if}
	{/if}

	<dl class="facts">
		{#if finding}
			<dt>Sessions</dt>
			<dd class="num">{fmt(finding.sessions)}</dd>
			<dt>Last seen</dt>
			<dd class="num">{formatWhen(finding.last_seen)}</dd>
		{/if}
		<dt>{finding ? 'Devices' : 'Used by'}</dt>
		<dd>
			{#each holder?.clients ?? [] as ip (ip)}
				<!-- OLD CODE START: <a href={device(ip)} title={ip}>{deviceName(ip, names)}</a> (NET-160: a client can be an internet address) OLD CODE END -->
				<a href={$ipHref(ip)} title={ip}>{deviceName(ip, names)}</a>
			{:else}
				<span class="dim">None recorded</span>
			{/each}
			{#if holder && holder.clients_total > holder.clients.length}
				<span class="dim">and {fmt(holder.clients_total - holder.clients.length)} more</span>
			{/if}
		</dd>
		<dt>Servers</dt>
		<dd>
			{#each servers as ip (ip)}
				<!-- OLD CODE START: <a class="mono" href={connections(ip)}>{ip}</a> (NET-160: a server opens its address page) OLD CODE END -->
				<a class="mono" href={$ipHref(ip)}>{ip}</a>
			{:else}
				<span class="dim">—</span>
			{/each}
		</dd>
	</dl>

	<div class="actions">
		{#if server}
			<a class="btn primary" href={connections(server)}><Icon name="connections" />View connections</a>
		{/if}
		{#if finding?.kind === 'device-expiry' && finding.server}
			<a class="btn" href={device(finding.server)}><Icon name="devices" />View device</a>
		{/if}
		{#if hostName}
			<a class="btn" href="/tools/ssl-cert?host={encodeURIComponent(hostName)}"><Icon name="certs" />Check it now</a>
		{/if}
		{#if siteLink}
			<a class="btn" href={siteLink.href}>{siteLink.label}</a>
		{/if}
	</div>

	<section class="certs" aria-label="Certificates">
		<h3>{certCount === 1 ? 'Certificate' : `Certificates (${fmt(certCount)})`}</h3>
		{#each fingerprints as fp, i (fp)}
			{@const cert = details[fp]}
			<div class="cert">
				{#if fingerprints.length > 1}<p class="dim">Certificate {i + 1}</p>{/if}
				{#if !cert}
					<p class="dim">This certificate isn't in the loaded figures.</p>
				{:else}
					{#if !cert.details_available}
						<p class="notice is-warn"><Icon name="warn" />Details unavailable: NetTap has no stored record of this certificate's issuer and dates. Its sessions are still counted.</p>
					{/if}
					<dl class="facts">
						{#if cert.details_available}
							<dt>Issued to</dt>
							<dd class="wrap">{cert.subject || '—'}</dd>
							<dt>Issued by</dt>
							<dd class="wrap">{cert.authority ?? '—'}{cert.self_signed ? ' (self-signed)' : ''}</dd>
							<dt>Valid</dt>
							<dd class="num">{formatDay(cert.not_before)} to {formatDay(cert.not_after)}</dd>
							<dt>Key</dt>
							<dd class="mono wrap">{key(cert)}</dd>
						{/if}
						<dt>Verification</dt>
						<dd class="wrap">{statusList(cert.statuses)}</dd>
						<dt>Encryption</dt>
						<dd class="mono wrap">{versions(cert)}</dd>
						<dt>Sessions, all sites</dt>
						<dd class="num">{fmt(cert.sessions)}</dd>
						<dt>First and last seen</dt>
						<dd class="num">{formatWhen(cert.first_seen)} to {formatWhen(cert.last_seen)}</dd>
						<dt>Sites</dt>
						<!-- OLD CODE START (NET-160: each site links where it drills down)
						<dd class="mono wrap">{cert.sites.map((s) => (s.startsWith('no-sni:') ? s.slice(7) : s)).join(', ') || '—'}{cert.sites_total > cert.sites.length ? ` and ${fmt(cert.sites_total - cert.sites.length)} more` : ''}</dd>
						OLD CODE END -->
						<dd class="mono wrap">
							{#each cert.sites as s (s)}<a href={certSiteHref(s)}>{s.startsWith('no-sni:') ? s.slice(7) : s}</a>{:else}—{/each}{#if cert.sites_total > cert.sites.length}<span class="dim">and {fmt(cert.sites_total - cert.sites.length)} more</span>{/if}
						</dd>
						<dt>SHA-256</dt>
						<dd class="mono wrap">{cert.fingerprint}</dd>
					</dl>
				{/if}
			</div>
		{/each}
		{#if certCount > fingerprints.length}
			<p class="dim">And {fmt(certCount - fingerprints.length)} more certificates, not listed here.</p>
		{/if}
	</section>
</aside>

<style>
	/* Layout glue: the sticky column scrolls on its own when taller than the viewport */
	.cert-detail { align-self: start; max-height: calc(100dvh - var(--sp-8)); overflow-y: auto; }
	.cert-detail .facts dd { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: var(--sp-1) var(--sp-2); text-align: right; }
	.wrap { overflow-wrap: anywhere; }
	.certs { border-top: 1px solid var(--line); padding-top: var(--sp-3); }
	.certs h3 { margin: 0 0 var(--sp-2); font-size: var(--text-sm); color: var(--text-2); }
	.cert + .cert { border-top: 1px solid var(--line); margin-top: var(--sp-3); padding-top: var(--sp-3); }
	@container app (max-width: 1100px) {
		.cert-detail { max-height: none; overflow: visible; }
	}
</style>
