/**
 * The Security posture category pages' fixed text: what each category is, why it matters for a home
 * or small-business network, good habits, and where to read more. Sources are government security
 * agencies (CISA, NIST, NCSC), EFF, MITRE and vendor documentation only; every URL was checked to
 * resolve to the page named here on 2026-11-16.
 */
import type { PostureSlug } from './score';

export interface LearnMoreLink {
	label: string;
	source: string;
	url: string;
}

export interface PostureGuide {
	/** One line under the page title */
	summary: string;
	what: string;
	why: string;
	practices: string[];
	learnMore: LearnMoreLink[];
}

export const GUIDES: Record<PostureSlug, PostureGuide> = {
	encryption: {
		summary: 'How much of your network’s traffic is scrambled so that nobody along the way can read it',
		what:
			'Encryption scrambles traffic so only the two ends of a connection can read it. Websites use it as HTTPS (the padlock in your browser); apps, video calls, VPNs and remote logins use the same idea. Traffic sent without it travels as plain text.',
		why:
			'Anything sent in plain text can be read, or quietly changed, by anyone on the path: someone on the same Wi-Fi, a compromised device in your home, or a network between you and the other end. For a home that means passwords and messages; for a small business it also means customer data.',
		practices: [
			'Keep phones, computers, smart devices and your router updated: updates add and enforce encryption.',
			'Turn on your browser’s HTTPS-only (or “always use secure connections”) setting.',
			'Prefer apps and devices that say they encrypt their traffic, and turn on any “secure” or “TLS” option they offer.',
			'Avoid old services that send passwords in plain text, such as Telnet and plain FTP.',
			'On public Wi-Fi, use a trusted VPN; at home it isn’t needed for this.',
		],
		learnMore: [
			{ label: 'What should I know about encryption?', source: 'EFF Surveillance Self-Defense', url: 'https://ssd.eff.org/module/what-should-i-know-about-encryption' },
			{ label: 'Using TLS to protect data', source: 'NCSC', url: 'https://www.ncsc.gov.uk/guidance/using-tls-to-protect-data' },
			{ label: 'Encrypt sensitive information (M1041)', source: 'MITRE ATT&CK', url: 'https://attack.mitre.org/mitigations/M1041/' },
			{ label: 'Choosing the VPN that’s right for you', source: 'EFF Surveillance Self-Defense', url: 'https://ssd.eff.org/module/choosing-vpn-thats-right-you' },
		],
	},
	'dns-security': {
		summary: 'Whether your devices look up website names privately, or in plain text anyone on the path can read',
		what:
			'Before a device connects to a website it asks a DNS server for the site’s address. Plain DNS sends that question as readable text. DNS-over-TLS (DoT) and DNS-over-HTTPS (DoH) send it encrypted, to a resolver you chose.',
		why:
			'Plain lookups show every site and service your devices use, and they can be answered falsely to send a device somewhere else. Using one trusted resolver with an encrypted upstream keeps that list private and lets the resolver block known-malicious sites for the whole network.',
		practices: [
			'Pick one resolver for the whole network (your router, or a local one such as Pi-hole or AdGuard Home) and give it an encrypted upstream (DoT or DoH).',
			'Choose an upstream that blocks known-malicious domains if you want that protection.',
			'On phones, turn on Private DNS (Android) or an encrypted DNS profile (iPhone) for when you’re away from home.',
			'Watch for devices that ignore your router and use their own DNS server.',
		],
		learnMore: [
			{ label: 'Encrypted DNS implementation guidance', source: 'CISA', url: 'https://www.cisa.gov/resources-tools/resources/encrypted-dns-implementation-guidance' },
			{ label: 'Protective DNS', source: 'NCSC', url: 'https://www.ncsc.gov.uk/information/pdns' },
			{ label: 'DNS, DoH, and ODoH, oh my', source: 'EFF', url: 'https://www.eff.org/deeplinks/2020/12/dns-doh-and-odoh-oh-my-year-review-2020' },
			{ label: 'Manage advanced network settings (Private DNS)', source: 'Android Help', url: 'https://support.google.com/android/answer/9654714' },
			{ label: 'DNS over TLS', source: 'Cloudflare 1.1.1.1 docs', url: 'https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-tls/' },
		],
	},
	'network-segmentation': {
		summary: 'Whether NetTap knows how each device normally behaves, and whether smart devices can reach your computers',
		what:
			'Segmentation means splitting a network into separate parts, for example one for computers and phones, one for smart devices and one for guests, so a device in one part can’t freely reach the others. NetTap also keeps a behaviour baseline for every device, so it can spot one acting unusually.',
		why:
			'Smart plugs, cameras and TVs get fewer security updates than computers. If one is taken over and sits on the same network as your laptop or a work computer, it can reach them directly. A separate network for those devices limits what an attacker can get to.',
		practices: [
			'Put smart devices on a guest or IoT network; most routers offer a guest Wi-Fi network for this.',
			'Turn on client (AP) isolation for the guest network, so devices on it can’t reach each other.',
			'Give visitors the guest network, not your main one.',
			'Turn off UPnP on the router unless something you rely on needs it.',
			'Change the router’s admin password from the default.',
		],
		learnMore: [
			{ label: 'Layering network security through segmentation', source: 'CISA', url: 'https://www.cisa.gov/resources-tools/resources/layering-network-security-through-segmentation-infographic' },
			{ label: 'Smart devices: using them safely in your home', source: 'NCSC', url: 'https://www.ncsc.gov.uk/guidance/smart-devices-in-the-home' },
			{ label: 'Home network security', source: 'CISA', url: 'https://www.cisa.gov/news-events/news/home-network-security' },
			{ label: 'Securing wireless networks', source: 'CISA', url: 'https://www.cisa.gov/news-events/news/securing-wireless-networks' },
			{ label: 'Network segmentation (M1030)', source: 'MITRE ATT&CK', url: 'https://attack.mitre.org/mitigations/M1030/' },
		],
	},
	'patch-currency': {
		summary: 'Signs of out-of-date devices: old protocols that modern, updated software no longer uses',
		what:
			'Patching means installing the updates makers release for software and firmware. NetTap can’t read a device’s software version, so this category looks for a sign instead: old protocols (plain HTTP, FTP, Telnet, POP3, IMAP) that updated software has mostly replaced with encrypted versions.',
		why:
			'Most successful attacks use flaws that already have a fix. Devices that are never updated, or that the maker has stopped supporting, keep those flaws for good. Old protocols on a device are often the first visible sign that it falls into that group.',
		practices: [
			'Turn on automatic updates on phones, computers, the router and smart devices.',
			'Check the router’s firmware for updates every month or two if it doesn’t update itself.',
			'Replace devices the maker no longer updates (look for an end-of-support date).',
			'When buying, prefer makers that say how long they will provide security updates.',
		],
		learnMore: [
			{ label: 'Update software', source: 'CISA', url: 'https://www.cisa.gov/secure-our-world/update-software' },
			{ label: 'Install the latest software and app updates', source: 'NCSC', url: 'https://www.ncsc.gov.uk/collection/top-tips-for-staying-secure-online/install-the-latest-software-and-app-updates' },
			{ label: 'Protecting your devices', source: 'NCSC small organisations guide', url: 'https://www.ncsc.gov.uk/collection/small-organisations-guide-to-cyber-security/protecting-your-devices' },
			{ label: 'Known exploited vulnerabilities catalog', source: 'CISA', url: 'https://www.cisa.gov/known-exploited-vulnerabilities-catalog' },
			{ label: 'Update software (M1051)', source: 'MITRE ATT&CK', url: 'https://attack.mitre.org/mitigations/M1051/' },
		],
	},
	'alert-response': {
		summary: 'Whether the alerts NetTap raises get looked at and closed',
		what:
			'NetTap’s intrusion detection (Suricata) raises an alert when traffic matches a known pattern of trouble: a known-bad address, malware traffic, a scan. An investigation is your record of looking into one: what you checked, what you found and what you did.',
		why:
			'An alert nobody reads protects nothing. Most alerts turn out to be harmless, but the rare real one only helps if someone checks it in time. Writing down what you checked also saves time when the same alert comes back.',
		practices: [
			'Look at high-severity alerts the same day, and the rest about once a week.',
			'Open an investigation for anything you look into, note what you found, and close it.',
			'Once you’ve confirmed an alert is expected activity, mark it as a false positive so it stops crowding out the rest.',
			'Keep the detection rules up to date in Settings.',
		],
		learnMore: [
			{ label: 'Spotting cyber attacks', source: 'NCSC small organisations guide', url: 'https://www.ncsc.gov.uk/collection/small-organisations-guide-to-cyber-security/spotting-cyber-attacks' },
			{ label: 'Incident response recommendations (SP 800-61 Rev. 3)', source: 'NIST', url: 'https://csrc.nist.gov/pubs/sp/800/61/r3/final' },
			{ label: 'Small business cybersecurity corner', source: 'NIST', url: 'https://www.nist.gov/itl/smallbusinesscyber' },
			{ label: 'Global thresholds (suppressing noisy rules)', source: 'Suricata documentation', url: 'https://docs.suricata.io/en/latest/configuration/global-thresholds.html' },
		],
	},
	'monitoring-coverage': {
		summary: 'How much of your network NetTap can see and keep an eye on',
		what:
			'NetTap can only report on traffic that reaches it. This category checks that every device it has seen has a risk score, and alongside that whether its sensors are running, whether it is missing packets, and what its position in your network lets it see.',
		why:
			'A gap in monitoring is a place where trouble goes unnoticed. A stopped sensor, a capture port that drops packets, or a device whose traffic never passes NetTap all look like “nothing happening” unless you check.',
		practices: [
			'Check the System page about once a week, and after power cuts or updates.',
			'Put NetTap where it sees the most: a mirror (SPAN) port of your main switch’s uplink shows each device.',
			'Keep NetTap on a UPS or a reliable power socket so it doesn’t miss what happens during an outage.',
			'Update NetTap when a new release is out.',
		],
		learnMore: [
			{ label: 'Best practices for event logging and threat detection', source: 'CISA', url: 'https://www.cisa.gov/resources-tools/resources/best-practices-event-logging-and-threat-detection' },
			{ label: 'Cybersecurity Framework', source: 'NIST', url: 'https://www.nist.gov/cyberframework' },
			{ label: 'Network traffic (DS0029)', source: 'MITRE ATT&CK', url: 'https://attack.mitre.org/datasources/DS0029/' },
		],
	},
};
