<script lang="ts">
	import { enhance } from '$app/forms';
	import { goto } from '$app/navigation';
	import Collapsible from '$components/Collapsible.svelte';
	import DhcpGatewayStep from '$components/setup/DhcpGatewayStep.svelte';
	import BrandMark from '$lib/components/shell/BrandMark.svelte';
	import Card from '$lib/components/ui/Card.svelte';
	import CardState from '$lib/components/ui/CardState.svelte';
	import Icon from '$lib/components/ui/Icon.svelte';
	import Meter from '$lib/components/ui/Meter.svelte';
	import { DEFAULT_DHCP_SUBNET } from '$lib/utils/dhcpSubnet';

	// OLD CODE START — was: const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8880';
	// Port 8880 is Docker-internal only. Use relative paths through SvelteKit proxy.
	// OLD CODE END
	const API_BASE = '';

	let { form } = $props();

	// ----- Wizard state -----
	let currentStep = $state(1);

	// OLD CODE START — fixed totalSteps / stepLabels for bridge-only wizard
	// const totalSteps = 5;
	// const stepLabels = ['Welcome', 'Interfaces', 'Bridge', 'Storage', 'Account'];
	// OLD CODE END

	// OLD CODE START — two modes only; DHCP gateway added 2026-10-30
	// // Capture mode: 'mirror' (Mirror/SPAN) or 'bridge' (Inline Bridge)
	// type CaptureMode = 'mirror' | 'bridge' | '';
	// OLD CODE END
	// Capture mode: 'dhcp_gateway' (DHCP Gateway), 'mirror' (Mirror/SPAN) or 'bridge' (Inline Bridge, under Advanced)
	type CaptureMode = 'dhcp_gateway' | 'mirror' | 'bridge' | '';
	let selectedMode = $state<CaptureMode>('');

	// Dynamic step labels based on mode
	// Mirror: Welcome -> Capture Mode -> Interfaces (mirror) -> Storage -> Enrichment -> Account -> Verification
	// Bridge: Welcome -> Capture Mode -> Interfaces (bridge) -> Bridge Config -> Storage -> Enrichment -> Account -> Verification
	// DHCP gateway: Welcome -> Capture Mode -> Interfaces (router port) -> DHCP Gateway -> Storage -> Enrichment -> Account -> Verification
	// Before mode selected: Welcome -> Capture Mode (only 2 steps available)
	let stepLabels = $derived.by(() => {
		if (selectedMode === 'mirror') {
			return ['Welcome', 'Capture Mode', 'Interfaces', 'Storage', 'Enrichment', 'Account', 'Verification'];
		} else if (selectedMode === 'bridge') {
			return ['Welcome', 'Capture Mode', 'Interfaces', 'Bridge', 'Storage', 'Enrichment', 'Account', 'Verification'];
		} else if (selectedMode === 'dhcp_gateway') {
			return ['Welcome', 'Capture Mode', 'Interfaces', 'DHCP Gateway', 'Storage', 'Enrichment', 'Account', 'Verification'];
		}
		return ['Welcome', 'Capture Mode'];
	});

	let totalSteps = $derived(stepLabels.length);

	// The step names above are the wizard's keys; on screen they read in sentence case
	const STEP_TITLES: Record<string, string> = { 'Capture Mode': 'Capture mode', 'DHCP Gateway': 'DHCP gateway' };
	function stepTitle(label: string): string {
		return STEP_TITLES[label] ?? label;
	}

	// ----- Step 1: Welcome -----
	let requirementsChecked = $state(false);
	let checkingRequirements = $state(false);
	let requirements = $state({
		nics: { label: 'One or more network interfaces', status: 'pending' as 'pending' | 'pass' | 'fail' },
		docker: { label: 'Docker is running', status: 'pending' as 'pending' | 'pass' | 'fail' },
		disk: { label: 'Sufficient disk space (100GB+)', status: 'pending' as 'pending' | 'pass' | 'fail' },
	});

	// Track detected NIC count for mode-dependent validation
	let detectedEthernetNicCount = $state(0);

	// ----- Step 3: Network Interfaces -----
	interface NetworkInterface {
		name: string;
		mac: string;
		state: 'up' | 'down' | 'unknown';
		speed: string;
		driver: string;
		ipv4?: string;
		type: 'ethernet' | 'wireless' | 'virtual' | 'loopback';
	}

	let interfaces = $state<NetworkInterface[]>([]);
	let nicsLoading = $state(false);
	let nicsError = $state('');
	let nicsSource = $state('');
	const NICS_UNREACHABLE = "Couldn't detect the network cards: NetTap's service didn't answer.";

	// Bridge mode NIC selection
	let selectedWan = $state('');
	let selectedLan = $state('');

	// Mirror mode NIC selection
	let selectedMirrorNic = $state('');
	let selectedManagementNic = $state('');

	// DHCP gateway NIC selection (the one port plugged into the router)
	let selectedDhcpNic = $state('');

	// Filter to only usable (non-loopback) interfaces for NIC selection
	let selectableInterfaces = $derived(
		interfaces.filter((iface) => iface.type !== 'loopback')
	);

	let selectedWanDetails = $derived(
		interfaces.find((iface) => iface.name === selectedWan)
	);

	let selectedLanDetails = $derived(
		interfaces.find((iface) => iface.name === selectedLan)
	);

	let selectedMirrorNicDetails = $derived(
		interfaces.find((iface) => iface.name === selectedMirrorNic)
	);

	let selectedManagementNicDetails = $derived(
		interfaces.find((iface) => iface.name === selectedManagementNic)
	);

	let selectedDhcpNicDetails = $derived(
		interfaces.find((iface) => iface.name === selectedDhcpNic)
	);

	let nicSelectionValid = $derived.by(() => {
		if (selectedMode === 'mirror') {
			return selectedMirrorNic !== '';
		}
		if (selectedMode === 'dhcp_gateway') {
			return selectedDhcpNic !== '';
		}
		return selectedWan !== '' && selectedLan !== '' && selectedWan !== selectedLan;
	});

	// ----- Step 4 (bridge mode): Bridge Configuration -----
	interface BridgeConfig {
		config_preview: string;
		wan: string;
		lan: string;
		bridge_name: string;
		ready: boolean;
		warnings: string[];
		source: string;
	}

	let bridgeConfig = $state<BridgeConfig | null>(null);
	let bridgeLoading = $state(false);
	let bridgeError = $state('');
	let bridgeVerified = $state(false);

	// ----- Step 4 (DHCP gateway mode): subnet NetTap hands out -----
	let dhcpSubnet = $state(DEFAULT_DHCP_SUBNET);
	let dhcpSubnetValid = $state(false);
	// The subnet must not contain any address NetTap already uses
	let dhcpNicAddresses = $derived(
		interfaces.map((iface) => iface.ipv4 || '').filter((ip) => ip !== '')
	);

	// ----- Storage Configuration -----
	interface StorageStatus {
		disk_total_gb: number;
		disk_used_gb: number;
		disk_free_gb: number;
		disk_usage_percent: number;
		hot_days: number;
		warm_days: number;
		cold_days: number;
		disk_threshold_percent: number;
		emergency_threshold_percent: number;
		estimated_daily_gb: number;
		source: string;
	}

	let storageStatus = $state<StorageStatus | null>(null);
	let storageLoading = $state(false);
	let storageError = $state('');
	let storageSaving = $state(false);
	let storageSaved = $state(false);

	let hotDays = $state(90);
	let warmDays = $state(180);
	let coldDays = $state(30);
	let diskThreshold = $state(80);
	let emergencyThreshold = $state(90);

	let estimatedTotalDays = $derived.by(() => {
		if (!storageStatus) return 0;
		const freeGb = storageStatus.disk_free_gb;
		const usableGb = freeGb * (diskThreshold / 100);
		const dailyGb = storageStatus.estimated_daily_gb || 1.2;
		return Math.floor(usableGb / dailyGb);
	});

	// OLD CODE START — 2026-11-03 redesign: the disk bar's colour by usage, from legacy tokens; the
	// bar is the system's Meter now and the percentage is written beside it
	// let diskUsageColor = $derived.by(() => {
	// 	if (!storageStatus) return 'var(--accent)';
	// 	if (storageStatus.disk_usage_percent >= 90) return 'var(--danger)';
	// 	if (storageStatus.disk_usage_percent >= 70) return 'var(--warning)';
	// 	return 'var(--success)';
	// });
	// OLD CODE END

	// ----- Device Enrichment (both modes) -----
	let useUnifi = $state(false);
	let unifiUrl = $state('');
	let unifiApiKey = $state('');
	let unifiTesting = $state(false);
	let unifiTestResult = $state<'success' | 'fail' | ''>('');
	let unifiTestError = $state('');

	// ----- Admin Account -----
	let adminLoading = $state(false);
	let adminUsername = $state('');
	let adminPassword = $state('');
	let adminConfirmPassword = $state('');
	let clientError = $state('');

	let passwordHasLength = $derived(adminPassword.length >= 8);
	let passwordHasUpper = $derived(/[A-Z]/.test(adminPassword));
	let passwordHasLower = $derived(/[a-z]/.test(adminPassword));
	let passwordHasNumber = $derived(/[0-9]/.test(adminPassword));
	let passwordsMatch = $derived(
		adminPassword !== '' && adminConfirmPassword !== '' && adminPassword === adminConfirmPassword
	);
	let passwordValid = $derived(
		passwordHasLength && passwordHasUpper && passwordHasLower && passwordHasNumber
	);
	let adminFormValid = $derived(
		adminUsername.trim().length >= 3 && passwordValid && passwordsMatch
	);

	// ----- Self-Traffic Exclusion -----
	let applianceIp = $state('');
	let applianceIpLoading = $state(false);
	let applianceIpSaved = $state(false);

	// ----- Post-Setup Health Verification -----
	let healthChecks = $state<Array<{label: string; status: 'pending' | 'checking' | 'pass' | 'fail' | 'warn'; detail: string}>>([]);
	let verificationRunning = $state(false);
	let verificationDone = $state(false);

	// ----- Saving config on completion -----
	let configSaving = $state(false);
	let configSaveError = $state('');
	let configSaveWarnings = $state<string[]>([]);

	// ----- Helper: get the logical step name for the current step number -----
	function getStepName(step: number): string {
		return stepLabels[step - 1] || '';
	}

	// ----- Navigation logic -----
	function canAdvance(): boolean {
		const stepName = getStepName(currentStep);
		switch (stepName) {
			case 'Welcome':
				return requirementsChecked;
			case 'Capture Mode':
				return selectedMode !== '';
			case 'Interfaces':
				return nicSelectionValid;
			case 'Bridge':
				return true; // Bridge verification is optional
			case 'DHCP Gateway':
				return dhcpSubnetValid;
			case 'Storage':
				return true; // Storage config has defaults
			case 'Enrichment':
				return true; // Enrichment is optional
			case 'Account':
				return false; // Step uses form submission, not Next
			case 'Verification':
				return false; // Uses custom navigation buttons
			default:
				return false;
		}
	}

	function nextStep(): void {
		if (currentStep < totalSteps && canAdvance()) {
			currentStep++;
			onStepEnter(currentStep);
		}
	}

	function prevStep(): void {
		if (currentStep > 1) {
			currentStep--;
		}
	}

	function goToStep(step: number): void {
		// Only allow going back to completed steps or the current step
		if (step <= currentStep && step >= 1) {
			currentStep = step;
			onStepEnter(step);
		}
	}

	function onStepEnter(step: number): void {
		const stepName = getStepName(step);
		if (stepName === 'Interfaces' && interfaces.length === 0) {
			fetchNics();
		}
		if (stepName === 'Storage') {
			if (!storageStatus) {
				fetchStorage();
			}
			fetchApplianceIp();
		}
	}

	// ----- Step 1: Check requirements -----
	async function checkRequirements(): Promise<void> {
		checkingRequirements = true;

		// Check NICs
		requirements.nics = { ...requirements.nics, status: 'pending' };
		requirements.docker = { ...requirements.docker, status: 'pending' };
		requirements.disk = { ...requirements.disk, status: 'pending' };

		try {
			const nicRes = await fetch('/api/setup/nics');
			if (!nicRes.ok) throw new Error(`HTTP ${nicRes.status}`);
			const text = await nicRes.text();
			let nicData: { interfaces?: NetworkInterface[]; source?: string };
			try {
				nicData = JSON.parse(text);
			} catch {
				throw new Error('Server returned invalid data');
			}
			// the proxy answers built-in sample cards when the daemon doesn't; they passed this check
			if (nicData.source === 'mock') throw new Error(NICS_UNREACHABLE);
			// Count non-loopback, non-virtual interfaces available
			const bridgeableNics = (nicData.interfaces || []).filter(
				(iface: NetworkInterface) => iface.type === 'ethernet'
			);
			detectedEthernetNicCount = bridgeableNics.length;

			// Before mode is selected, require at least 1 NIC (minimum for mirror)
			// Once mode is selected, mirror needs 1+, bridge needs 2+
			const minNics = selectedMode === 'bridge' ? 2 : 1;
			requirements.nics = {
				...requirements.nics,
				label: minNics >= 2 ? 'Two or more network interfaces' : 'One or more network interfaces',
				status: bridgeableNics.length >= minNics ? 'pass' : 'fail',
			};

			// Pre-populate interfaces for step 3
			interfaces = nicData.interfaces || [];
			nicsSource = nicData.source || '';
		} catch {
			// OLD CODE START — a failed check read as "you don't have the network cards"
			// requirements.nics = { ...requirements.nics, status: 'fail' };
			// OLD CODE END
			requirements.nics = { ...requirements.nics, label: "Network interfaces: couldn't check", status: 'fail' };
		}

		// OLD CODE START — every branch passed, a failed request included
		// // Check Docker — use the health endpoint
		// try {
		// 	const healthRes = await fetch('/api/health');
		// 	if (healthRes.ok) {
		// 		requirements.docker = { ...requirements.docker, status: 'pass' };
		// 	} else {
		// 		// Health endpoint exists but returned non-ok — still means server is running
		// 		requirements.docker = { ...requirements.docker, status: 'pass' };
		// 	}
		// } catch {
		// 	// In development, if the health endpoint works, we consider Docker "available"
		// 	requirements.docker = { ...requirements.docker, status: 'pass' };
		// }
		// OLD CODE END
		// /api/health always answers 200 from the web container; whether the daemon (and so the
		// Docker stack behind it) runs is in its `daemon` field
		try {
			const healthRes = await fetch('/api/health');
			if (!healthRes.ok) throw new Error(`HTTP ${healthRes.status}`);
			const health = await healthRes.json();
			const up = health?.daemon && health.daemon.status !== 'unreachable';
			requirements.docker = up
				? { ...requirements.docker, label: 'Docker is running', status: 'pass' }
				: { ...requirements.docker, label: "Docker: the NetTap daemon isn't answering", status: 'fail' };
		} catch {
			requirements.docker = { ...requirements.docker, label: "Docker: couldn't check", status: 'fail' };
		}

		// Check Disk via storage
		// OLD CODE START — a failed read passed, and so did the proxy's sample reply (911 GB free)
		// try {
		// 	const storageRes = await fetch('/api/setup/storage');
		// 	const storageData = await storageRes.json();
		// 	const freeGb = storageData.disk_free_gb || 0;
		// 	requirements.disk = {
		// 		...requirements.disk,
		// 		status: freeGb >= 100 ? 'pass' : 'fail',
		// 	};
		// } catch {
		// 	requirements.disk = { ...requirements.disk, status: 'pass' };
		// }
		// OLD CODE END
		try {
			const storageRes = await fetch('/api/setup/storage');
			if (!storageRes.ok) throw new Error(`HTTP ${storageRes.status}`);
			const storageData = await storageRes.json();
			if (storageData.source === 'mock' || typeof storageData.disk_free_gb !== 'number') {
				throw new Error('no disk reading');
			}
			requirements.disk = {
				...requirements.disk,
				status: storageData.disk_free_gb >= 100 ? 'pass' : 'fail',
			};
		} catch {
			requirements.disk = { ...requirements.disk, label: "Disk space: couldn't check", status: 'fail' };
		}

		requirementsChecked = true;
		checkingRequirements = false;
	}

	// ----- Step 3: Fetch NICs -----
	async function fetchNics(): Promise<void> {
		nicsLoading = true;
		nicsError = '';
		try {
			const res = await fetch('/api/setup/nics');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const text = await res.text();
			let data: { interfaces?: NetworkInterface[]; source?: string };
			try {
				data = JSON.parse(text);
			} catch {
				throw new Error('Server returned invalid data — daemon may need restart');
			}
			// OLD CODE START — offered the proxy's sample cards (eth0/eth1/wlan0) for selection when the daemon didn't answer
			// interfaces = data.interfaces || [];
			// nicsSource = data.source || '';
			// OLD CODE END
			if (data.source === 'mock') throw new Error(NICS_UNREACHABLE);
			interfaces = data.interfaces || [];
			nicsSource = data.source || '';
		} catch (err) {
			nicsError = err instanceof Error ? err.message : 'Failed to fetch interfaces';
		}
		nicsLoading = false;
	}

	// ----- Bridge verify -----
	async function verifyBridge(): Promise<void> {
		bridgeLoading = true;
		bridgeError = '';
		bridgeVerified = false;
		try {
			const res = await fetch('/api/setup/bridge', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					wan_interface: selectedWan,
					lan_interface: selectedLan,
				}),
			});
			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.error || `HTTP ${res.status}`);
			}
			bridgeConfig = await res.json();
			bridgeVerified = bridgeConfig?.ready ?? false;
			if (bridgeVerified && typeof window !== 'undefined') {
				localStorage.setItem('nettap_wan_iface', selectedWan);
				localStorage.setItem('nettap_lan_iface', selectedLan);
			}
		} catch (err) {
			bridgeError = err instanceof Error ? err.message : 'Failed to verify bridge configuration';
		}
		bridgeLoading = false;
	}

	// ----- Storage fetch/save -----
	async function fetchStorage(): Promise<void> {
		storageLoading = true;
		storageError = '';
		try {
			const res = await fetch('/api/setup/storage');
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			storageStatus = await res.json();
			// Initialize form values from server defaults
			if (storageStatus) {
				hotDays = storageStatus.hot_days;
				warmDays = storageStatus.warm_days;
				coldDays = storageStatus.cold_days;
				diskThreshold = storageStatus.disk_threshold_percent;
				emergencyThreshold = storageStatus.emergency_threshold_percent;
			}
		} catch (err) {
			storageError = err instanceof Error ? err.message : 'Failed to fetch storage status';
		}
		storageLoading = false;
	}

	async function saveStorage(): Promise<void> {
		storageSaving = true;
		storageError = '';
		storageSaved = false;
		try {
			const res = await fetch('/api/setup/storage', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					hot_days: hotDays,
					warm_days: warmDays,
					cold_days: coldDays,
					disk_threshold_percent: diskThreshold,
					emergency_threshold_percent: emergencyThreshold,
				}),
			});
			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.error || `HTTP ${res.status}`);
			}
			storageSaved = true;
		} catch (err) {
			storageError = err instanceof Error ? err.message : 'Failed to save storage configuration';
		}
		storageSaving = false;
	}

	// ----- Self-Traffic Exclusion: fetch current excluded IPs -----
	async function fetchApplianceIp(): Promise<void> {
		applianceIpLoading = true;
		try {
			const res = await fetch('/api/settings/excluded-ips');
			if (res.ok) {
				const data = await res.json();
				const ips = data.excluded_ips || [];
				if (ips.length > 0) applianceIp = ips[0];
			}
		} catch { /* ignore */ }
		applianceIpLoading = false;
	}

	// ----- Device Enrichment: test UniFi connection -----
	async function testUnifiConnection(): Promise<void> {
		unifiTesting = true;
		unifiTestResult = '';
		unifiTestError = '';
		try {
			// Step 1: Configure the UniFi integration (sets URL + API key on the daemon)
			const configRes = await fetch(`${API_BASE}/api/integrations/unifi/configure`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					controller_url: unifiUrl,
					api_key: unifiApiKey,
				}),
			});
			if (!configRes.ok) {
				const configData = await configRes.json();
				throw new Error(configData.error || `Configure failed: HTTP ${configRes.status}`);
			}

			// Step 2: Test the connection (now that the daemon has the credentials)
			const res = await fetch(`${API_BASE}/api/integrations/unifi/test`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					controller_url: unifiUrl,
					api_key: unifiApiKey,
				}),
			});
			// OLD CODE START — the daemon answers 200 with success:false for a bad key
			// if (!res.ok) {
			// 	const data = await res.json();
			// 	throw new Error(data.error || `HTTP ${res.status}`);
			// }
			// OLD CODE END
			const data = await res.json().catch(() => ({}));
			if (!res.ok || !data.success) {
				throw new Error(data.error || data.status?.last_error || `Connection test failed (HTTP ${res.status})`);
			}
			unifiTestResult = 'success';
		} catch (err) {
			unifiTestResult = 'fail';
			unifiTestError = err instanceof Error ? err.message : 'Connection test failed';
		}
		unifiTesting = false;
	}

	// ----- Post-Setup Health Verification -----
	async function runVerification(): Promise<void> {
		verificationRunning = true;
		verificationDone = false;
		healthChecks = [
			{ label: 'NetTap daemon', status: 'checking', detail: 'Checking…' },
			{ label: 'OpenSearch', status: 'checking', detail: 'Checking…' },
			{ label: 'Self-traffic exclusion', status: 'checking', detail: 'Checking…' },
		];
		if (selectedMode === 'bridge') {
			healthChecks.push({ label: 'Bridge health', status: 'checking', detail: 'Checking…' });
		}
		if (useUnifi) {
			healthChecks.push({ label: 'UniFi controller', status: 'checking', detail: 'Checking…' });
		}

		// Check NetTap Daemon
		// OLD CODE START — F6: /api/health answers 200 from the web container even with the daemon
		// down, so this said "Running" whenever the web app was up
		// try {
		// 	const healthRes = await fetch('/api/health');
		// 	healthChecks[0] = healthRes.ok
		// 		? { label: 'NetTap daemon', status: 'pass', detail: 'Running' }
		// 		: { label: 'NetTap daemon', status: 'fail', detail: 'Not responding' };
		// } catch { healthChecks[0] = { label: 'NetTap daemon', status: 'fail', detail: 'Unreachable' }; }
		// OLD CODE END
		// Whether the daemon answered is in `daemon.status`, as in the requirements check
		try {
			const healthRes = await fetch('/api/health');
			if (!healthRes.ok) throw new Error(`HTTP ${healthRes.status}`);
			const health = await healthRes.json();
			healthChecks[0] = health?.daemon && health.daemon.status !== 'unreachable'
				? { label: 'NetTap daemon', status: 'pass', detail: 'Running' }
				: { label: 'NetTap daemon', status: 'fail', detail: 'Not responding' };
		} catch { healthChecks[0] = { label: 'NetTap daemon', status: 'fail', detail: 'Unreachable' }; }

		// Check OpenSearch
		try {
			const osRes = await fetch('/api/opensearch/cluster');
			if (osRes.ok) {
				const osData = await osRes.json();
				const status = osData.status || 'unknown';
				healthChecks[1] = { label: 'OpenSearch', status: status === 'red' ? 'fail' : 'pass', detail: `Cluster: ${status}` };
			} else {
				healthChecks[1] = { label: 'OpenSearch', status: 'fail', detail: 'Not responding' };
			}
		} catch { healthChecks[1] = { label: 'OpenSearch', status: 'fail', detail: 'Unreachable' }; }

		// Check Self-Traffic Exclusion
		try {
			const exRes = await fetch('/api/settings/excluded-ips');
			if (exRes.ok) {
				const exData = await exRes.json();
				const count = (exData.excluded_ips || []).length;
				healthChecks[2] = { label: 'Self-traffic exclusion', status: count > 0 ? 'pass' : 'warn', detail: count > 0 ? `${count} IP(s) excluded` : 'No IPs configured' };
			} else {
				// OLD CODE: no else branch — a non-OK response left the row "Checking..." forever (2026-10-29)
				healthChecks[2] = { label: 'Self-traffic exclusion', status: 'warn', detail: `Could not check (HTTP ${exRes.status})` };
			}
		} catch { healthChecks[2] = { label: 'Self-traffic exclusion', status: 'warn', detail: 'Could not check' }; }

		// Bridge check (if applicable)
		let idx = 3;
		if (selectedMode === 'bridge') {
			try {
				const brRes = await fetch('/api/bridge/health');
				if (brRes.ok) {
					const brData = await brRes.json();
					// OLD CODE START — the daemon never sends `healthy`, so this row always warned (2026-10-29)
					// healthChecks[idx] = { label: 'Bridge Health', status: brData.healthy ? 'pass' : 'warn', detail: brData.healthy ? 'Bridge active' : 'Bridge not fully healthy' };
					// OLD CODE END
					const bridgeNormal = brData.health_status === 'normal';
					healthChecks[idx] = { label: 'Bridge health', status: bridgeNormal ? 'pass' : 'warn', detail: bridgeNormal ? 'Bridge active' : 'Bridge not fully healthy' };
				} else {
					healthChecks[idx] = { label: 'Bridge health', status: 'warn', detail: `Could not check (HTTP ${brRes.status})` };
				}
			} catch { healthChecks[idx] = { label: 'Bridge health', status: 'warn', detail: 'Could not check' }; }
			idx++;
		}

		// UniFi check (if configured)
		if (useUnifi) {
			try {
				const uRes = await fetch('/api/integrations/unifi/status');
				if (uRes.ok) {
					const uData = await uRes.json();
					// OLD CODE START — "configured" was reported as connected before any poll succeeded (2026-10-29)
					// healthChecks[idx] = { label: 'UniFi Controller', status: uData.configured ? 'pass' : 'warn', detail: uData.configured ? `Connected (${uData.cache_counts?.clients || 0} clients)` : 'Not configured' };
					// OLD CODE END
					const unifiDetail = uData.connected
						? `Connected (${uData.cache_counts?.clients || 0} clients)`
						: uData.configured ? 'Configured, not connected yet' : 'Not configured';
					healthChecks[idx] = { label: 'UniFi controller', status: uData.connected ? 'pass' : 'warn', detail: unifiDetail };
				} else {
					healthChecks[idx] = { label: 'UniFi controller', status: 'warn', detail: `Could not check (HTTP ${uRes.status})` };
				}
			} catch { healthChecks[idx] = { label: 'UniFi controller', status: 'warn', detail: 'Could not check' }; }
		}

		verificationRunning = false;
		verificationDone = true;
	}

	// ----- Save setup configuration -----
	async function saveSetupConfig(): Promise<void> {
		configSaving = true;
		configSaveError = '';
		configSaveWarnings = [];
		try {
			const payload: Record<string, unknown> = {
				capture_mode: selectedMode,
			};

			if (selectedMode === 'mirror') {
				payload.capture_interface = selectedMirrorNic;
				if (selectedManagementNic) {
					payload.management_interface = selectedManagementNic;
				}
			} else if (selectedMode === 'dhcp_gateway') {
				payload.capture_interface = selectedDhcpNic;
				payload.dhcp_subnet = dhcpSubnet;
			} else {
				payload.wan_interface = selectedWan;
				payload.lan_interface = selectedLan;
			}

			// UniFi enrichment applies to both modes
			if (useUnifi) {
				payload.unifi = {
					url: unifiUrl,
					api_key: unifiApiKey,
				};
			}

			payload.storage = {
				hot_days: hotDays,
				warm_days: warmDays,
				cold_days: coldDays,
				disk_threshold_percent: diskThreshold,
				emergency_threshold_percent: emergencyThreshold,
			};

			const res = await fetch(`${API_BASE}/api/setup/configure`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload),
			});
			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.error || `HTTP ${res.status}`);
			}
			// res.ok alone isn't "all saved": the daemon answers "partial" when e.g. retention wasn't written
			const saved: { status?: string; warnings?: string[] } = await res.json();
			if (saved.status === 'partial') {
				configSaveWarnings = saved.warnings?.length ? saved.warnings : ['Some settings were not saved.'];
			}
		} catch (err) {
			configSaveError = err instanceof Error ? err.message : 'Failed to save configuration';
		}
		configSaving = false;
	}

	// ----- Handle form result for Account step -----
	$effect(() => {
		if (form?.success) {
			// Account created — save config then advance to Verification step
			saveSetupConfig().then(() => {
				currentStep = totalSteps; // Verification is the last step
				runVerification();
			});
		}
		if (form?.error) {
			adminLoading = false;
		}
	});

	// Auto-run requirements check when page loads
	$effect(() => {
		if (!requirementsChecked && !checkingRequirements) {
			checkRequirements();
		}
	});
</script>

<svelte:head>
	<title>Setup Wizard | NetTap</title>
</svelte:head>

{#snippet spinner()}<span class="spinner" aria-hidden="true"></span>{/snippet}

{#snippet nicDetails(iface: NetworkInterface, showState: boolean, showIp: boolean)}
	<div class="chips nic-details">
		<span class="tag">{iface.driver || 'unknown'}</span>
		<span class="tag">{iface.speed || 'N/A'}</span>
		{#if showState}
			<span class="chip nic-state" class:is-ok={iface.state === 'up'} class:is-bad={iface.state === 'down'}>{iface.state}</span>
		{/if}
		{#if showIp && iface.ipv4}
			<span class="tag">{iface.ipv4}</span>
		{/if}
	</div>
{/snippet}

{#snippet nicNotices()}
	{#if nicsSource === 'mock'}
		<div class="notice is-warn">
			<Icon name="warn" />
			<span>Daemon unavailable: showing sample interface data. The real interfaces are detected on the NetTap device.</span>
		</div>
	{/if}
	{#if nicsError}
		<div class="notice is-error">
			<Icon name="warn" />
			<span class="grow">{nicsError}</span>
			<button class="btn" onclick={fetchNics} type="button">Retry</button>
		</div>
	{/if}
{/snippet}

<!-- Bare route (no shell): the wizard in cards under a pill step indicator -->
<div class="wizard">
	<header class="page-head">
		<div class="wizard-title">
			<BrandMark />
			<div>
				<h1 class="page-title">Set up NetTap</h1>
				<p class="page-sub">
					{selectedMode ? `Step ${currentStep} of ${totalSteps}` : `Step ${currentStep}`} · {stepTitle(getStepName(currentStep))}
				</p>
			</div>
		</div>
	</header>

	<!-- Step indicator: the system's pill track. Done steps go back; later steps are disabled. -->
	<nav class="step-nav" aria-label="Setup progress">
		<ol class="pills">
			{#each stepLabels as label, i}
				{@const stepNum = i + 1}
				<li>
					<button
						class="pill"
						type="button"
						disabled={stepNum > currentStep}
						aria-current={stepNum === currentStep ? 'step' : undefined}
						onclick={() => goToStep(stepNum)}
					>
						{#if stepNum < currentStep}
							<Icon name="check" label="Done" />
						{:else}
							<span class="step-num">{stepNum}</span>
						{/if}
						<span class="step-label">{stepTitle(label)}</span>
					</button>
				</li>
			{/each}
		</ol>
	</nav>

	<!-- ===== STEP: Welcome ===== -->
	{#if getStepName(currentStep) === 'Welcome'}
		<Card title="Welcome to NetTap" hero>
			<div class="stack">
				<p class="lead">
					NetTap is a network visibility appliance that gives you enterprise-grade network telemetry in a
					web dashboard, without needing deep networking knowledge.
				</p>

				<section class="panel">
					<h3 class="sub-title">What this wizard sets up</h3>
					<ol class="steps">
						<!-- OLD CODE START — listed two modes; DHCP gateway added 2026-10-30
						<li>Choose your capture mode (Mirror/SPAN or Inline Bridge)</li>
						OLD CODE END -->
						<li>Choose your capture mode (DHCP gateway, Mirror / SPAN, or inline bridge under Advanced)</li>
						<li>Detect and select network interfaces</li>
						<li>Set up storage retention</li>
						<li>Create your admin account</li>
					</ol>
				</section>

				<section class="stack">
					<h3 class="sub-title">System requirements</h3>
					<ul class="checklist">
						{#each Object.values(requirements) as req}
							<li class="check is-{req.status}">
								<span class="check-icon">
									{#if req.status === 'pending'}
										<span class="pending-dot" role="img" aria-label="Checking"></span>
									{:else if req.status === 'pass'}
										<Icon name="check" label="Passed" />
									{:else}
										<Icon name="close" label="Failed" />
									{/if}
								</span>
								<span class="check-name">{req.label}</span>
							</li>
						{/each}
					</ul>

					{#if !requirementsChecked}
						<div class="actions">
							<button class="btn primary" onclick={checkRequirements} disabled={checkingRequirements} type="button">
								{#if checkingRequirements}
									{@render spinner()}Checking…
								{:else}
									Check requirements
								{/if}
							</button>
						</div>
					{:else}
						<div class="notice">
							<Icon name="check" />
							<span>Requirements checked. Select Get started to continue.</span>
						</div>
					{/if}
				</section>
			</div>
		</Card>

	<!-- ===== STEP: Capture Mode ===== -->
	{:else if getStepName(currentStep) === 'Capture Mode'}
		<Card title="Choose capture mode">
			<div class="stack">
				<p class="lead">
					Select how NetTap captures network traffic. This decides the hardware setup and what traffic
					NetTap can see.
				</p>

				<div class="mode-cards">
					<button
						class="mode-card"
						class:selected={selectedMode === 'dhcp_gateway'}
						aria-pressed={selectedMode === 'dhcp_gateway'}
						onclick={() => { selectedMode = 'dhcp_gateway'; }}
						type="button"
					>
						<!-- OLD CODE: <span class="chip is-ok">Recommended</span> (NET-225: this mode has never run on hardware; mirror is the tested one) -->
						<span class="mode-top">
							<span class="tile"><Icon name="connections" /></span>
							<span class="chip is-caution">Not yet tested on hardware</span>
						</span>
						<span class="mode-name">DHCP gateway</span>
						<span class="mode-desc">
							NetTap hands out addresses to your devices and passes their traffic on to your router.
							Works with any router, no special switch needed.
						</span>
						<ul class="mode-features">
							<li>Requires 1 NIC, plugged into your router</li>
							<li>You turn off your router's DHCP at Go Live</li>
							<li>See traffic per device, with each device's own address</li>
							<li>Devices with a fixed IP address bypass NetTap</li>
						</ul>
					</button>

					<button
						class="mode-card"
						class:selected={selectedMode === 'mirror'}
						aria-pressed={selectedMode === 'mirror'}
						onclick={() => { selectedMode = 'mirror'; }}
						type="button"
					>
						<!-- OLD CODE START — Mirror was the recommended mode until DHCP gateway (2026-10-30)
						<div class="mode-badge recommended">Recommended</div>
						OLD CODE END -->
						<!-- OLD CODE: <span class="mode-top"><span class="tile"><Icon name="live" /></span></span> (NET-225: say it is the tested mode) -->
						<span class="mode-top">
							<span class="tile"><Icon name="live" /></span>
							<span class="chip is-ok">Tested on hardware</span>
						</span>
						<span class="mode-name">Mirror / SPAN</span>
						<span class="mode-desc">
							My managed switch sends a copy of network traffic to NetTap. Zero risk to your network.
							Best for per-device visibility.
						</span>
						<ul class="mode-features">
							<li>Requires 1 NIC for capture</li>
							<li>No inline risk: the switch does the mirroring</li>
							<li>See traffic per device on the LAN</li>
						</ul>
					</button>
				</div>

				<!-- Inline bridge stays available, but only under Advanced; open when it is the current choice -->
				<Collapsible
					title="Advanced"
					subtitle="Put NetTap between your modem and router (needs two NICs)"
					expanded={selectedMode === 'bridge'}
				>
					<div class="mode-cards">
						<button
							class="mode-card"
							class:selected={selectedMode === 'bridge'}
							aria-pressed={selectedMode === 'bridge'}
							onclick={() => { selectedMode = 'bridge'; }}
							type="button"
						>
							<!-- OLD CODE START — NET-225: left out that, after the router's address translation, devices can't be told apart
							<span class="mode-top"><span class="tile"><Icon name="infra" /></span></span>
							NetTap sits between your modem and router. Sees all WAN traffic. Requires two dedicated NICs.
							<li>Sees all WAN ingress and egress</li>
							OLD CODE END -->
							<span class="mode-top">
								<span class="tile"><Icon name="infra" /></span>
								<span class="chip is-caution">Not yet tested on hardware</span>
							</span>
							<span class="mode-name">Inline bridge</span>
							<span class="mode-desc">
								NetTap sits between your modem and router and sees all internet traffic, but after your router's
								address translation, so all your devices' IPv4 traffic shows up as the router. Requires two
								dedicated NICs.
							</span>
							<ul class="mode-features">
								<li>Requires 2 NICs (WAN + LAN)</li>
								<li>Transparent Layer 2 bridge</li>
								<li>No per-device view: devices share the router's IPv4 address</li>
							</ul>
						</button>
					</div>
				</Collapsible>

				{#if selectedMode === 'bridge' && detectedEthernetNicCount < 2}
					<div class="notice is-warn">
						<Icon name="warn" />
						<span>
							Bridge mode requires 2 Ethernet NICs, but only {detectedEthernetNicCount} were detected. You may
							continue, but bridge configuration will fail without 2 NICs.
						</span>
					</div>
				{/if}
			</div>
		</Card>

	<!-- ===== STEP: Interfaces (mode-dependent) ===== -->
	{:else if getStepName(currentStep) === 'Interfaces'}
		{#if selectedMode === 'mirror'}
			<!-- Mirror mode: select capture NIC + optional management NIC -->
			<Card title="Select capture interface">
				<div class="stack">
					<p class="lead">
						Choose the network interface that receives the mirrored (SPAN) traffic from your switch. This NIC
						gets no IP address: it captures traffic in promiscuous mode.
					</p>
					{@render nicNotices()}

					{#if nicsLoading}
						<CardState state="loading" title="Detecting network interfaces" />
					{:else}
						<div class="diagram" aria-hidden="true">
							<span class="node"><span class="tile"><Icon name="infra" /></span><span class="node-label">Switch</span></span>
							<span class="cable"></span>
							<span class="node" class:selected={selectedMirrorNic !== ''}>
								<span class="tile"><Icon name="connections" /></span><span class="node-label mono">{selectedMirrorNic || 'Capture NIC'}</span>
							</span>
							<span class="cable"></span>
							<span class="node"><span class="tile accent"><Icon name="system" /></span><span class="node-label">NetTap</span></span>
						</div>

						<div class="form-grid">
							<div class="field">
								<label for="mirror-select" class="label">
									Capture interface <span class="dim">(receives mirrored traffic)</span>
								</label>
								<select id="mirror-select" class="select" bind:value={selectedMirrorNic}>
									<option value="">Select the capture interface</option>
									{#each selectableInterfaces as iface}
										<option value={iface.name} disabled={iface.name === selectedManagementNic}>
											{iface.name} ({iface.mac}) - {iface.speed || 'unknown speed'} [{iface.state}]
										</option>
									{/each}
								</select>
								{#if selectedMirrorNicDetails}
									{@render nicDetails(selectedMirrorNicDetails, true, false)}
									<div class="notice">
										<Icon name="connections" />
										<span>This NIC gets no IP address. It captures traffic in promiscuous mode only.</span>
									</div>
								{/if}
							</div>

							<div class="field">
								<label for="mgmt-select" class="label">
									Management interface <span class="dim">(optional, for dashboard access)</span>
								</label>
								<select id="mgmt-select" class="select" bind:value={selectedManagementNic}>
									<option value="">Auto-detect (default)</option>
									{#each selectableInterfaces as iface}
										<option value={iface.name} disabled={iface.name === selectedMirrorNic}>
											{iface.name} ({iface.mac}) - {iface.speed || 'unknown speed'} [{iface.state}]
											{#if iface.ipv4} ({iface.ipv4}){/if}
										</option>
									{/each}
								</select>
								{#if selectedManagementNicDetails}
									{@render nicDetails(selectedManagementNicDetails, false, true)}
								{/if}
							</div>
						</div>

						<div class="actions">
							<button class="btn" onclick={fetchNics} type="button"><Icon name="refresh" />Refresh interfaces</button>
						</div>
					{/if}
				</div>
			</Card>
		{:else if selectedMode === 'dhcp_gateway'}
			<!-- DHCP gateway mode: the one NIC plugged into the router -->
			<Card title="Select router port">
				<div class="stack">
					<p class="lead">
						Choose the port plugged into your router. NetTap keeps its current address on this port and hands
						out addresses to your devices through it.
					</p>
					{@render nicNotices()}

					{#if nicsLoading}
						<CardState state="loading" title="Detecting network interfaces" />
					{:else}
						<div class="form-grid">
							<div class="field">
								<label for="dhcp-nic-select" class="label">
									Router port <span class="dim">(the port plugged into your router)</span>
								</label>
								<select id="dhcp-nic-select" class="select" bind:value={selectedDhcpNic}>
									<option value="">Select the port plugged into your router</option>
									{#each selectableInterfaces as iface}
										<option value={iface.name}>
											{iface.name} ({iface.mac}) - {iface.speed || 'unknown speed'} [{iface.state}]
											{#if iface.ipv4} ({iface.ipv4}){/if}
										</option>
									{/each}
								</select>
								{#if selectedDhcpNicDetails}
									{@render nicDetails(selectedDhcpNicDetails, true, true)}
									{#if !selectedDhcpNicDetails.ipv4}
										<div class="notice is-warn">
											<Icon name="warn" />
											<span>
												This port has no IPv4 address. NetTap needs an address from your router on this port to
												pass traffic on. Check that it's plugged into your router, then refresh.
											</span>
										</div>
									{/if}
								{/if}
							</div>
						</div>

						<div class="actions">
							<button class="btn" onclick={fetchNics} type="button"><Icon name="refresh" />Refresh interfaces</button>
						</div>
					{/if}
				</div>
			</Card>
		{:else}
			<!-- Bridge mode: WAN + LAN NIC selection (original flow) -->
			<Card title="Select network interfaces">
				<div class="stack">
					<p class="lead">
						Choose the network interfaces for the WAN (modem) and LAN (router) connections. NetTap creates a
						transparent bridge between them.
					</p>
					{@render nicNotices()}

					{#if nicsLoading}
						<CardState state="loading" title="Detecting network interfaces" />
					{:else}
						<div class="diagram" aria-hidden="true">
							<span class="node"><span class="tile"><Icon name="dns" /></span><span class="node-label">Modem</span></span>
							<span class="cable"></span>
							<span class="node" class:selected={selectedWan !== ''}>
								<span class="tile"><Icon name="connections" /></span><span class="node-label mono">{selectedWan || 'WAN NIC'}</span>
							</span>
							<span class="cable"></span>
							<span class="node"><span class="tile accent"><Icon name="system" /></span><span class="node-label">NetTap bridge</span></span>
							<span class="cable"></span>
							<span class="node" class:selected={selectedLan !== ''}>
								<span class="tile"><Icon name="connections" /></span><span class="node-label mono">{selectedLan || 'LAN NIC'}</span>
							</span>
							<span class="cable"></span>
							<span class="node"><span class="tile"><Icon name="infra" /></span><span class="node-label">Router</span></span>
						</div>

						<div class="form-grid">
							<div class="field">
								<label for="wan-select" class="label">WAN interface <span class="dim">(connects to modem)</span></label>
								<select id="wan-select" class="select" bind:value={selectedWan}>
									<option value="">Select the WAN interface</option>
									{#each selectableInterfaces as iface}
										<option value={iface.name} disabled={iface.name === selectedLan}>
											{iface.name} ({iface.mac}) - {iface.speed || 'unknown speed'} [{iface.state}]
										</option>
									{/each}
								</select>
								{#if selectedWanDetails}
									{@render nicDetails(selectedWanDetails, true, true)}
								{/if}
							</div>

							<div class="field">
								<label for="lan-select" class="label">LAN interface <span class="dim">(connects to router)</span></label>
								<select id="lan-select" class="select" bind:value={selectedLan}>
									<option value="">Select the LAN interface</option>
									{#each selectableInterfaces as iface}
										<option value={iface.name} disabled={iface.name === selectedWan}>
											{iface.name} ({iface.mac}) - {iface.speed || 'unknown speed'} [{iface.state}]
										</option>
									{/each}
								</select>
								{#if selectedLanDetails}
									{@render nicDetails(selectedLanDetails, true, true)}
								{/if}
							</div>
						</div>

						{#if selectedWan && selectedLan && selectedWan === selectedLan}
							<div class="notice is-error"><Icon name="warn" /><span>WAN and LAN interfaces must be different.</span></div>
						{/if}

						<div class="actions">
							<button class="btn" onclick={fetchNics} type="button"><Icon name="refresh" />Refresh interfaces</button>
						</div>
					{/if}
				</div>
			</Card>
		{/if}

	<!-- ===== STEP: Bridge Configuration (bridge mode only) ===== -->
	{:else if getStepName(currentStep) === 'Bridge'}
		<Card title="Bridge configuration">
			<div class="stack">
				<p class="lead">
					Review and verify the bridge configuration. NetTap creates a transparent Layer 2 bridge between your
					selected interfaces.
				</p>

				<dl class="facts">
					<dt>WAN interface</dt>
					<dd class="mono">{selectedWan}</dd>
					<dt>LAN interface</dt>
					<dd class="mono">{selectedLan}</dd>
					<dt>Bridge name</dt>
					<dd class="mono">br0</dd>
					<dt>Mode</dt>
					<dd>Transparent (Layer 2 forwarding)</dd>
				</dl>

				{#if bridgeError}
					<div class="notice is-error"><Icon name="warn" /><span>{bridgeError}</span></div>
				{/if}

				{#if bridgeConfig && bridgeVerified}
					<div class="notice is-ok"><Icon name="check" /><span>Configuration verified.</span></div>

					{#if bridgeConfig.warnings.length > 0}
						<div class="notice is-warn">
							<Icon name="warn" />
							<span>
								{#each bridgeConfig.warnings as warning}
									<span class="line">{warning}</span>
								{/each}
							</span>
						</div>
					{/if}

					<section>
						<h3 class="eyebrow">Configuration preview</h3>
						<pre class="preview mono">{bridgeConfig.config_preview}</pre>
					</section>
				{/if}

				<div class="actions">
					<button class="btn primary" onclick={verifyBridge} disabled={bridgeLoading} type="button">
						{#if bridgeLoading}
							{@render spinner()}Verifying…
						{:else if bridgeVerified}
							Verify configuration again
						{:else}
							Verify configuration
						{/if}
					</button>
				</div>

				<div class="notice">
					<Icon name="system" />
					<span>
						The bridge is configured when you finish the setup wizard and start NetTap's services. Nothing on
						your network changes until then.
					</span>
				</div>
			</div>
		</Card>

	<!-- ===== STEP: DHCP Gateway (dhcp_gateway mode only) ===== -->
	{:else if getStepName(currentStep) === 'DHCP Gateway'}
		<Card title="DHCP gateway">
			<div class="stack">
				<p class="lead">
					Pick the address range NetTap gives your devices. Keep the default unless your network already uses it.
				</p>

				<DhcpGatewayStep
					bind:subnet={dhcpSubnet}
					bind:valid={dhcpSubnetValid}
					nicAddresses={dhcpNicAddresses}
					selectedInterface={selectedDhcpNic}
				/>
			</div>
		</Card>

	<!-- ===== STEP: Storage Configuration ===== -->
	{:else if getStepName(currentStep) === 'Storage'}
		<Card title="Storage configuration">
			<div class="stack">
				<p class="lead">
					Set how long NetTap keeps data and when it starts freeing disk space. NetTap keeps data in three tiers.
				</p>

				{#if storageError}
					<div class="notice is-error"><Icon name="warn" /><span>{storageError}</span></div>
				{/if}

				{#if storageLoading}
					<CardState state="loading" title="Loading storage information" />
				{:else if storageStatus}
					<section class="panel stack">
						<div class="panel-head">
							<h3 class="sub-title">Disk usage</h3>
							<span class="num">{storageStatus.disk_usage_percent}% used</span>
						</div>
						<Meter value={storageStatus.disk_usage_percent} label="Disk used" />
						<div class="disk-stats num">
							<span>{storageStatus.disk_used_gb.toFixed(1)} GB used</span>
							<span>{storageStatus.disk_free_gb.toFixed(1)} GB free</span>
							<span>{storageStatus.disk_total_gb.toFixed(1)} GB total</span>
						</div>

						{#if estimatedTotalDays > 0}
							<p class="estimate">
								Estimated retention capacity: <strong class="num">{estimatedTotalDays} days</strong>
								<span class="dim">at about {storageStatus.estimated_daily_gb} GB a day</span>
							</p>
						{/if}
					</section>

					<div class="form-grid">
						<section class="panel tier">
							<h3 class="tier-name"><span class="sw c-d1" aria-hidden="true"></span>Hot tier</h3>
							<!-- OLD CODE START — 2026-11-02: alerts share the Zeek index (see Settings → Retention)
							<p class="text-muted tier-desc">Zeek metadata logs (conn, DNS, HTTP, TLS, etc.)</p>
							OLD CODE END -->
							<p class="tier-desc">Zeek logs (conn, DNS, HTTP, TLS, etc.) and Suricata alerts, kept in one daily index</p>
							<div class="field">
								<label for="hot-days" class="label">Retention (days)</label>
								<input id="hot-days" type="number" class="input" bind:value={hotDays} min="1" max="365" />
							</div>
							<span class="tier-size">About 300 to 800 MB a day</span>
						</section>

						<section class="panel tier">
							<h3 class="tier-name"><span class="sw c-d2" aria-hidden="true"></span>Warm tier</h3>
							<!-- OLD CODE START
							<p class="text-muted tier-desc">Suricata IDS alerts and signatures</p>
							OLD CODE END -->
							<p class="tier-desc">Separate <span class="mono">suricata-*</span> indices only. This install doesn't create them; alerts follow the Hot tier</p>
							<div class="field">
								<label for="warm-days" class="label">Retention (days)</label>
								<input id="warm-days" type="number" class="input" bind:value={warmDays} min="1" max="730" />
							</div>
							<span class="tier-size">About 10 to 50 MB a day</span>
						</section>

						<section class="panel tier">
							<h3 class="tier-name"><span class="sw c-d3" aria-hidden="true"></span>Cold tier</h3>
							<!-- OLD CODE START — 2026-11-02: capture is continuous (owner decision, #37)
							<p class="text-muted tier-desc">Raw PCAP files (alert-triggered only)</p>
							OLD CODE END -->
							<p class="tier-desc">Raw PCAP files of all traffic, also capped by disk share</p>
							<div class="field">
								<label for="cold-days" class="label">Retention (days)</label>
								<input id="cold-days" type="number" class="input" bind:value={coldDays} min="1" max="365" />
							</div>
							<span class="tier-size">Variable size</span>
						</section>
					</div>

					<section class="panel stack">
						<h3 class="sub-title">Disk thresholds</h3>
						<p class="tier-desc">
							When disk usage passes the warning threshold, NetTap deletes old data, starting with the oldest
							tier. The emergency threshold triggers immediate cleanup.
						</p>

						<div class="form-grid">
							<div class="field">
								<label for="disk-threshold" class="label range-label">
									Warning threshold <span class="chip is-warn num">{diskThreshold}%</span>
								</label>
								<input id="disk-threshold" type="range" class="range" bind:value={diskThreshold} min="50" max="95" step="1" />
								<div class="range-ends num"><span>50%</span><span>95%</span></div>
							</div>

							<div class="field">
								<label for="emergency-threshold" class="label range-label">
									Emergency threshold <span class="chip is-bad num">{emergencyThreshold}%</span>
								</label>
								<input
									id="emergency-threshold"
									type="range"
									class="range"
									bind:value={emergencyThreshold}
									min={diskThreshold + 1}
									max="99"
									step="1"
								/>
								<div class="range-ends num"><span>{diskThreshold + 1}%</span><span>99%</span></div>
							</div>
						</div>
					</section>

					<div class="actions">
						<button class="btn primary" onclick={saveStorage} disabled={storageSaving} type="button">
							{#if storageSaving}
								{@render spinner()}Saving…
							{:else}
								Save storage settings
							{/if}
						</button>
						{#if storageSaved}
							<span class="chip is-ok"><Icon name="check" />Saved</span>
						{/if}
					</div>

					<!-- Self-traffic exclusion -->
					<section class="field exclusion">
						<label for="appliance-ip" class="label">Self-traffic exclusion</label>
						<p class="field-help">
							Your appliance's IP is excluded from every dashboard, so NetTap's own traffic doesn't add noise.
						</p>
						<div class="inline-field">
							<input
								id="appliance-ip"
								type="text"
								class="input mono"
								bind:value={applianceIp}
								placeholder="Detected on startup…"
							/>
							{#if applianceIp}
								<span class="chip is-ok"><Icon name="check" />Detected</span>
							{:else}
								<span class="chip">Set with the MGMT_IP variable</span>
							{/if}
						</div>
					</section>
				{/if}
			</div>
		</Card>

	<!-- ===== STEP: Device Enrichment (both modes) ===== -->
	{:else if getStepName(currentStep) === 'Enrichment'}
		<Card title="Device enrichment">
			<div class="stack">
				<p class="lead">
					NetTap identifies devices on your network passively (MAC vendor, DHCP fingerprints, mDNS and more). You
					can also connect a UniFi controller for richer device names and details.
				</p>

				<label class="panel toggle-row">
					<span class="toggle-text">
						<strong>Do you use UniFi network equipment?</strong>
						<span class="field-help">Connect your UniFi controller for better device identification.</span>
					</span>
					<input type="checkbox" class="switch" bind:checked={useUnifi} />
				</label>

				{#if useUnifi}
					<section class="panel stack">
						<h3 class="sub-title">UniFi controller</h3>

						<div class="field">
							<label for="unifi-url" class="label">Controller URL</label>
							<input
								id="unifi-url"
								type="url"
								class="input mono"
								placeholder="https://192.168.1.1:8443"
								bind:value={unifiUrl}
							/>
							<span class="field-help">The URL of your UniFi controller or Dream Machine.</span>
						</div>

						<div class="field">
							<label for="unifi-api-key" class="label">API key</label>
							<input
								id="unifi-api-key"
								type="password"
								class="input"
								placeholder="Paste your UniFi API key"
								bind:value={unifiApiKey}
								autocomplete="off"
							/>
							<span class="field-help">Create an API key in your UniFi controller under Settings → Integrations.</span>
						</div>

						{#if unifiTestResult === 'success'}
							<div class="notice is-ok"><Icon name="check" /><span>Successfully connected to UniFi controller.</span></div>
						{:else if unifiTestResult === 'fail'}
							<div class="notice is-error"><Icon name="warn" /><span>Connection failed: {unifiTestError}</span></div>
						{/if}

						<div class="actions">
							<button
								class="btn primary"
								onclick={testUnifiConnection}
								disabled={unifiTesting || !unifiUrl || !unifiApiKey}
								type="button"
							>
								{#if unifiTesting}
									{@render spinner()}Testing…
								{:else}
									Test connection
								{/if}
							</button>
						</div>
					</section>
				{:else}
					<section class="panel">
						<h3 class="sub-title">Passive identification (automatic)</h3>
						<p class="tier-desc">Without UniFi, NetTap still identifies devices using:</p>
						<ul class="steps bullets">
							<li>MAC address vendor lookup (the manufacturer)</li>
							<li>DHCP fingerprinting (OS and device type)</li>
							<li>mDNS and SSDP discovery (device names)</li>
							<li>HTTP User-Agent analysis</li>
							<li>TLS fingerprinting (JA3/JA4)</li>
						</ul>
					</section>
				{/if}
			</div>
		</Card>

	<!-- ===== STEP: Admin Account ===== -->
	{:else if getStepName(currentStep) === 'Account'}
		<Card title="Create admin account">
			<div class="stack">
				<p class="lead">Create your administrator account. You use it to sign in to the NetTap dashboard.</p>

				{#if form?.error || clientError || configSaveError}
					<div class="notice is-error" role="alert">
						<Icon name="warn" />
						<span>{form?.error || clientError || configSaveError}</span>
					</div>
				{/if}

				{#if form?.success}
					<div class="notice is-ok">
						<Icon name="check" />
						<span>Admin account created. Running system verification…</span>
					</div>
				{:else}
					<form
						class="stack"
						method="POST"
						action="?/createAdmin"
						use:enhance={() => {
							clientError = '';

							// Client-side validation
							if (adminUsername.trim().length < 3) {
								clientError = 'Username must be at least 3 characters.';
								return ({ update }) => { update({ reset: false }); };
							}
							if (!passwordValid) {
								clientError = 'Password does not meet requirements.';
								return ({ update }) => { update({ reset: false }); };
							}
							if (!passwordsMatch) {
								clientError = 'Passwords do not match.';
								return ({ update }) => { update({ reset: false }); };
							}

							adminLoading = true;
							return async ({ result, update }) => {
								adminLoading = false;
								if (result.type === 'error') {
									clientError = `Server error (${result.status}). Check browser console for details.`;
								}
								await update({ reset: false });
							};
						}}
					>
						<div class="field">
							<label for="username" class="label">Username</label>
							<input
								id="username"
								name="username"
								type="text"
								class="input"
								placeholder="admin"
								required
								autocomplete="username"
								minlength="3"
								bind:value={adminUsername}
							/>
							<span class="field-help">At least 3 characters. Letters, numbers, hyphens and underscores.</span>
						</div>

						<div class="field">
							<label for="password" class="label">Password</label>
							<input
								id="password"
								name="password"
								type="password"
								class="input"
								placeholder="Choose a strong password"
								required
								minlength="8"
								autocomplete="new-password"
								bind:value={adminPassword}
							/>
						</div>

						<div class="field">
							<label for="confirmPassword" class="label">Confirm password</label>
							<input
								id="confirmPassword"
								name="confirmPassword"
								type="password"
								class="input"
								placeholder="Confirm your password"
								required
								minlength="8"
								autocomplete="new-password"
								bind:value={adminConfirmPassword}
							/>
						</div>

						<!-- Password requirements: the icon's label and the colour both say met or not -->
						<section class="panel">
							<h3 class="eyebrow">Password requirements</h3>
							<ul class="reqs">
								{#each [
									{ met: passwordHasLength, text: 'At least 8 characters' },
									{ met: passwordHasUpper, text: 'One uppercase letter' },
									{ met: passwordHasLower, text: 'One lowercase letter' },
									{ met: passwordHasNumber, text: 'One number' },
									{ met: passwordsMatch, text: 'Passwords match' },
								] as req (req.text)}
									<li class:met={req.met}>
										<Icon name={req.met ? 'check' : 'close'} label={req.met ? 'Met' : 'Not met'} />
										<span>{req.text}</span>
									</li>
								{/each}
							</ul>
						</section>

						<div class="actions">
							<button type="submit" class="btn primary" disabled={adminLoading || !adminFormValid || configSaving}>
								{#if adminLoading || configSaving}
									{@render spinner()}{configSaving ? 'Saving configuration…' : 'Creating account…'}
								{:else}
									Complete setup
								{/if}
							</button>
						</div>
					</form>
				{/if}
			</div>
		</Card>

	<!-- ===== STEP: Verification ===== -->
	{:else if getStepName(currentStep) === 'Verification'}
		<Card title="System verification">
			<div class="stack">
				<p class="lead">Checking that all services are running correctly…</p>

				{#if configSaveWarnings.length > 0}
					<div class="notice is-warn" role="alert">
						<Icon name="warn" />
						<div class="stack tight">
							<span><strong>Setup is only partly done.</strong> Your capture settings were saved, but not everything else was:</span>
							<ul class="config-warnings">
								{#each configSaveWarnings as warning}
									<li>{warning}</li>
								{/each}
							</ul>
							<div>
								<button class="btn" type="button" onclick={saveSetupConfig} disabled={configSaving}>
									{configSaving ? 'Saving…' : 'Try saving again'}
								</button>
							</div>
						</div>
					</div>
				{/if}

				{#if configSaveError}
					<div class="notice is-error" role="alert">
						<Icon name="warn" />
						<div class="stack tight">
							<span><strong>Your capture settings were not saved.</strong> {configSaveError}</span>
							<div>
								<button class="btn" type="button" onclick={saveSetupConfig} disabled={configSaving}>
									{configSaving ? 'Saving…' : 'Try saving again'}
								</button>
							</div>
						</div>
					</div>
				{/if}

				<ul class="checklist">
					{#each healthChecks as check}
						<li class="check is-{check.status}">
							<span class="check-icon">
								{#if check.status === 'checking' || check.status === 'pending'}
									<!-- the detail beside it says "Checking…" -->
									<span class="pending-dot" class:pulse={check.status === 'checking'} aria-hidden="true"></span>
								{:else if check.status === 'pass'}
									<Icon name="check" label="Passed" />
								{:else if check.status === 'warn'}
									<Icon name="warn" label="Warning" />
								{:else}
									<Icon name="close" label="Failed" />
								{/if}
							</span>
							<span class="check-name grow">{check.label}</span>
							<span class="check-detail">{check.detail}</span>
						</li>
					{/each}
				</ul>

				{#if verificationDone}
					<div class="actions">
						<a href="/" class="btn primary">Go to dashboard</a>
						<!-- OLD CODE START — offered Go Live even when the capture settings failed to save (2026-10-30)
						<a href="/go-live" class="btn btn-secondary">Go Live Setup</a>
						OLD CODE END -->
						<!-- Go Live acts on the saved capture mode, so wait for a successful save -->
						{#if !configSaveError}
							<a href="/go-live" class="btn">Go Live setup</a>
						{/if}
					</div>
				{/if}
			</div>
		</Card>
	{/if}

	<!-- Navigation buttons -->
	{#if (getStepName(currentStep) !== 'Account' && getStepName(currentStep) !== 'Verification') || form?.success}
		<div class="wizard-nav">
			{#if currentStep > 1 && !form?.success}
				<button class="btn" onclick={prevStep} type="button"><Icon name="back" />Back</button>
			{:else}
				<span></span>
			{/if}

			{#if getStepName(currentStep) !== 'Account' && getStepName(currentStep) !== 'Verification'}
				<div class="actions">
					{#if getStepName(currentStep) === 'Bridge' || getStepName(currentStep) === 'Storage' || getStepName(currentStep) === 'Enrichment'}
						<button class="btn" onclick={nextStep} type="button">Skip</button>
					{/if}
					<button class="btn primary" onclick={nextStep} disabled={!canAdvance()} type="button">
						{currentStep === 1 ? 'Get started' : 'Next'}<Icon name="back" class="chev" />
					</button>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.wizard {
		display: flex;
		flex-direction: column;
		gap: var(--sp-5);
	}

	.wizard-title {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
	}

	.grow {
		flex: 1;
		min-width: 0;
	}

	.lead {
		color: var(--text-2);
		font-size: var(--text-sm);
		line-height: 1.6;
	}

	.sub-title {
		font: 500 var(--text-base)/1.3 var(--font-display);
		margin-bottom: var(--sp-2);
	}

	.stack.tight {
		gap: var(--sp-2);
	}

	/* An inner box inside a step card (cards don't nest) */
	.panel {
		padding: var(--sp-4);
		border-radius: var(--r-md);
		background: var(--surface-1);
		border: 1px solid var(--line);
	}

	.panel-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--sp-3);
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.panel-head .sub-title {
		margin: 0;
	}

	/* ----- Step indicator: the pill track. A step is aria-current="step", so it gets the light pill here ----- */
	.step-nav {
		max-width: 100%;
		overflow-x: auto;
	}

	.step-nav ol {
		list-style: none;
		margin: 0;
	}

	.step-nav .pill {
		gap: var(--sp-2);
	}

	.step-nav .pill[aria-current='step'] {
		background: var(--pill-active-bg);
		color: var(--on-light);
	}

	.step-nav .pill:disabled {
		cursor: default;
	}

	.step-nav .pill :global(.ic) {
		width: 14px;
		height: 14px;
		stroke-width: 2.2;
		color: var(--ok);
	}

	.step-num {
		font-variant-numeric: tabular-nums;
		opacity: 0.8;
	}

	/* ----- Lists ----- */
	.steps {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		margin: 0;
		padding-left: var(--sp-6);
		font-size: var(--text-sm);
		color: var(--text-2);
		line-height: 1.6;
	}

	.steps.bullets {
		list-style: disc;
	}

	.checklist {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.check {
		display: flex;
		align-items: center;
		gap: var(--sp-3);
		padding: var(--sp-2) 0;
		border-bottom: 1px solid var(--line);
		font-size: var(--text-sm);
	}

	.check:last-child {
		border-bottom: 0;
	}

	.check-icon {
		display: inline-grid;
		place-items: center;
		width: 18px;
		flex: none;
		color: var(--text-3);
	}

	.check.is-pass .check-icon {
		color: var(--ok);
	}

	.check.is-fail .check-icon {
		color: var(--sev-critical);
	}

	.check.is-warn .check-icon {
		color: var(--sev-medium);
	}

	.check-name {
		font-weight: 600;
	}

	.check-detail {
		color: var(--text-2);
		font-size: var(--text-xs);
		text-align: right;
	}

	.pending-dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		border: 2px solid var(--text-3);
	}

	.pending-dot.pulse {
		border-color: var(--sev-medium);
		animation: pulse-dot 1s var(--ease) infinite alternate;
	}

	@keyframes pulse-dot {
		to {
			opacity: 0.35;
		}
	}

	.spinner {
		width: 14px;
		height: 14px;
		flex: none;
		border-radius: 50%;
		border: 2px solid currentColor;
		border-right-color: transparent;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* ----- Capture mode cards ----- */
	.mode-cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: var(--sp-4);
	}

	.mode-card {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--sp-2);
		padding: var(--sp-5);
		text-align: left;
		cursor: pointer;
		color: var(--text-1);
		background: var(--surface-1);
		border: 1px solid var(--line);
		border-radius: var(--r-lg);
		transition: background var(--dur-fast), border-color var(--dur-fast);
	}

	.mode-card:hover {
		background: var(--surface-2);
	}

	.mode-card.selected {
		background: var(--surface-2);
		border-color: var(--accent);
		box-shadow: inset 0 0 0 1px var(--accent);
	}

	.mode-card.selected .tile {
		color: var(--accent);
	}

	.mode-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
	}

	.mode-name {
		font: 500 var(--text-md)/1.3 var(--font-display);
	}

	.mode-desc {
		font-size: var(--text-sm);
		color: var(--text-2);
		line-height: 1.5;
	}

	.mode-features {
		margin: 0;
		padding-left: var(--sp-5);
		font-size: var(--text-xs);
		color: var(--text-3);
		line-height: 1.7;
	}

	/* ----- Network diagrams ----- */
	.diagram {
		display: flex;
		align-items: center;
		justify-content: center;
		flex-wrap: wrap;
		gap: var(--sp-3);
		padding: var(--sp-5);
		border-radius: var(--r-md);
		background: var(--surface-1);
		border: 1px solid var(--line);
	}

	.node {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--sp-1);
	}

	.node.selected .tile,
	.tile.accent {
		color: var(--accent);
	}

	.node-label {
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--text-2);
	}

	.cable {
		width: var(--sp-8);
		height: 2px;
		border-radius: var(--r-pill);
		background: var(--line-strong);
	}

	.nic-details {
		margin-top: var(--sp-1);
	}

	.chip.nic-state {
		text-transform: capitalize;
	}

	/* ----- Bridge ----- */
	.preview {
		margin: 0;
		padding: var(--sp-3) var(--sp-4);
		border-radius: var(--r-md);
		background: var(--surface-1);
		border: 1px solid var(--line);
		color: var(--text-1);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	.line {
		display: block;
	}

	/* ----- Storage ----- */
	.disk-stats {
		display: flex;
		flex-wrap: wrap;
		gap: var(--sp-1) var(--sp-4);
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.estimate {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.estimate strong {
		color: var(--text-1);
	}

	.tier {
		display: flex;
		flex-direction: column;
		gap: var(--sp-3);
	}

	.tier-name {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
		font: 500 var(--text-base)/1.3 var(--font-display);
	}

	.tier-desc {
		font-size: var(--text-sm);
		color: var(--text-2);
		line-height: 1.5;
	}

	.tier-size {
		margin-top: auto;
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.range-label {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--sp-2);
	}

	.range {
		width: 100%;
		accent-color: var(--accent);
		cursor: pointer;
	}

	.range:focus-visible {
		outline: 2px solid var(--focus);
		outline-offset: 2px;
	}

	.range-ends {
		display: flex;
		justify-content: space-between;
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.exclusion {
		padding-top: var(--sp-4);
		border-top: 1px solid var(--line);
	}

	.inline-field {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
	}

	/* ----- Enrichment ----- */
	.toggle-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--sp-4);
		cursor: pointer;
	}

	.toggle-text {
		display: flex;
		flex-direction: column;
		gap: var(--sp-1);
		font-size: var(--text-sm);
	}

	/* ----- Account ----- */
	.reqs {
		list-style: none;
		margin: var(--sp-2) 0 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
		gap: var(--sp-1) var(--sp-4);
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.reqs li {
		display: flex;
		align-items: center;
		gap: var(--sp-2);
	}

	.reqs li :global(.ic) {
		width: 14px;
		height: 14px;
		stroke-width: 2.2;
		color: var(--sev-critical);
	}

	.reqs li.met {
		color: var(--text-1);
	}

	.reqs li.met :global(.ic) {
		color: var(--ok);
	}

	/* ----- Verification ----- */
	.config-warnings {
		margin: 0;
		padding-left: var(--sp-5);
	}

	/* ----- Navigation ----- */
	.wizard-nav {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--sp-3);
		flex-wrap: wrap;
	}

	@media (max-width: 760px) {
		.check {
			flex-wrap: wrap;
		}

		.check-detail {
			width: 100%;
			padding-left: calc(18px + var(--sp-3));
			text-align: left;
		}
	}
</style>
