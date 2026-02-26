/**
 * Server-side notification dispatcher.
 *
 * Supports three channels:
 *   - Email (via nodemailer, dynamic import with graceful fallback)
 *   - Webhook (POST JSON to configured URL)
 *   - In-app (local JSON file store)
 *
 * Configuration is loaded from environment variables:
 *   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, NOTIFY_EMAIL
 *   NOTIFY_WEBHOOK_URL
 *   NOTIFY_INAPP_ENABLED (default true)
 *   NOTIFY_SEVERITY_THRESHOLD (1=critical, 2=high, 3=medium, 4=low; default 3)
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NotificationConfig {
	email: {
		enabled: boolean;
		recipients: string[];
		smtpHost: string;
		smtpPort: number;
		smtpUser: string;
		smtpPass: string;
		smtpFrom: string;
	};
	webhook: {
		enabled: boolean;
		url: string;
	};
	inApp: {
		enabled: boolean;
	};
	severityThreshold: number; // 1=critical, 2=high, 3=medium, 4=low
}

export interface Notification {
	id: string;
	type: 'alert' | 'system' | 'storage';
	severity: 'critical' | 'high' | 'medium' | 'low';
	title: string;
	message: string;
	timestamp: string;
	read: boolean;
	source?: {
		src_ip?: string;
		dest_ip?: string;
		signature?: string;
	};
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SEVERITY_LEVELS: Record<string, number> = {
	critical: 1,
	high: 2,
	medium: 3,
	low: 4,
};

const DATA_DIR = process.env.NETTAP_DATA_DIR || '/var/lib/nettap';
const NOTIFICATIONS_FILE = join(DATA_DIR, 'notifications.json');
const MAX_STORED_NOTIFICATIONS = 200;

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/**
 * Load notification configuration from environment variables.
 */
export function loadConfig(): NotificationConfig {
	const emailRecipients = process.env.NOTIFY_EMAIL;
	const smtpHost = process.env.SMTP_HOST || '';

	return {
		email: {
			enabled: Boolean(smtpHost && emailRecipients),
			recipients: emailRecipients ? emailRecipients.split(',').map((s) => s.trim()) : [],
			smtpHost,
			smtpPort: parseInt(process.env.SMTP_PORT || '587', 10),
			smtpUser: process.env.SMTP_USER || '',
			smtpPass: process.env.SMTP_PASS || '',
			smtpFrom: process.env.SMTP_FROM || 'nettap@localhost',
		},
		webhook: {
			enabled: Boolean(process.env.NOTIFY_WEBHOOK_URL),
			url: process.env.NOTIFY_WEBHOOK_URL || '',
		},
		inApp: {
			enabled: process.env.NOTIFY_INAPP_ENABLED !== 'false',
		},
		severityThreshold: parseInt(process.env.NOTIFY_SEVERITY_THRESHOLD || '3', 10),
	};
}

// ---------------------------------------------------------------------------
// In-app notification store (JSON file)
// ---------------------------------------------------------------------------

function ensureDataDir(): void {
	const dir = dirname(NOTIFICATIONS_FILE);
	if (!existsSync(dir)) {
		try {
			mkdirSync(dir, { recursive: true });
		} catch {
			// Best-effort; data dir may not be writable in dev
		}
	}
}

function readStore(): Notification[] {
	try {
		if (existsSync(NOTIFICATIONS_FILE)) {
			const raw = readFileSync(NOTIFICATIONS_FILE, 'utf-8');
			return JSON.parse(raw) as Notification[];
		}
	} catch {
		// Corrupted file or missing — start fresh
	}
	return [];
}

function writeStore(notifications: Notification[]): void {
	ensureDataDir();
	try {
		writeFileSync(NOTIFICATIONS_FILE, JSON.stringify(notifications, null, 2), 'utf-8');
	} catch {
		// Best-effort; may not be writable in dev
	}
}

// ---------------------------------------------------------------------------
// In-memory fallback when filesystem is not available
// ---------------------------------------------------------------------------

let memoryStore: Notification[] | null = null;

function getStore(): Notification[] {
	if (memoryStore !== null) return memoryStore;
	const fromDisk = readStore();
	if (fromDisk.length > 0) return fromDisk;
	memoryStore = [];
	return memoryStore;
}

function persistStore(notifications: Notification[]): void {
	memoryStore = notifications;
	writeStore(notifications);
}

// ---------------------------------------------------------------------------
// Email dispatch (dynamic nodemailer import)
// ---------------------------------------------------------------------------

async function sendEmail(
	config: NotificationConfig['email'],
	notification: Notification
): Promise<void> {
	try {
		// Dynamic import — nodemailer is an optional dependency.
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		const nodemailer: any = await (Function('return import("nodemailer")')() as Promise<any>);
		const transporter = nodemailer.createTransport({
			host: config.smtpHost,
			port: config.smtpPort,
			secure: config.smtpPort === 465,
			auth:
				config.smtpUser && config.smtpPass
					? { user: config.smtpUser, pass: config.smtpPass }
					: undefined,
		});

		const severityEmoji: Record<string, string> = {
			critical: '[CRITICAL]',
			high: '[HIGH]',
			medium: '[MEDIUM]',
			low: '[LOW]',
		};

		const prefix = severityEmoji[notification.severity] || '';

		await transporter.sendMail({
			from: config.smtpFrom,
			to: config.recipients.join(', '),
			subject: `${prefix} NetTap: ${notification.title}`,
			text: [
				`Severity: ${notification.severity.toUpperCase()}`,
				`Type: ${notification.type}`,
				`Time: ${notification.timestamp}`,
				'',
				notification.message,
				'',
				notification.source?.signature
					? `Signature: ${notification.source.signature}`
					: '',
				notification.source?.src_ip
					? `Source IP: ${notification.source.src_ip}`
					: '',
				notification.source?.dest_ip
					? `Dest IP: ${notification.source.dest_ip}`
					: '',
			]
				.filter(Boolean)
				.join('\n'),
			html: [
				`<h2 style="color: ${notification.severity === 'critical' ? '#f85149' : notification.severity === 'high' ? '#d29922' : '#58a6ff'}">${prefix} ${notification.title}</h2>`,
				`<p><strong>Severity:</strong> ${notification.severity.toUpperCase()}</p>`,
				`<p><strong>Type:</strong> ${notification.type}</p>`,
				`<p><strong>Time:</strong> ${notification.timestamp}</p>`,
				`<p>${notification.message}</p>`,
				notification.source?.signature
					? `<p><strong>Signature:</strong> ${notification.source.signature}</p>`
					: '',
				notification.source?.src_ip
					? `<p><strong>Source IP:</strong> <code>${notification.source.src_ip}</code></p>`
					: '',
				notification.source?.dest_ip
					? `<p><strong>Dest IP:</strong> <code>${notification.source.dest_ip}</code></p>`
					: '',
			]
				.filter(Boolean)
				.join('\n'),
		});
	} catch (err) {
		console.error(
			'[notifications] Email dispatch failed:',
			err instanceof Error ? err.message : err
		);
	}
}

// ---------------------------------------------------------------------------
// Webhook dispatch
// ---------------------------------------------------------------------------

async function sendWebhook(url: string, notification: Notification): Promise<void> {
	try {
		await fetch(url, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				event: 'nettap.notification',
				notification,
			}),
			signal: AbortSignal.timeout(10_000),
		});
	} catch (err) {
		console.error(
			'[notifications] Webhook dispatch failed:',
			err instanceof Error ? err.message : err
		);
	}
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Generate a unique notification ID.
 */
function generateId(): string {
	return `ntf_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Dispatch a notification to all configured channels.
 * Returns the notification with its assigned ID.
 */
export async function sendNotification(
	notification: Omit<Notification, 'id' | 'timestamp' | 'read'>
): Promise<Notification> {
	const config = loadConfig();
	const severityLevel = SEVERITY_LEVELS[notification.severity] ?? 4;

	const full: Notification = {
		...notification,
		id: generateId(),
		timestamp: new Date().toISOString(),
		read: false,
	};

	// Check severity threshold
	if (severityLevel > config.severityThreshold) {
		// Still store in-app but don't send external notifications
		if (config.inApp.enabled) {
			storeInApp(full);
		}
		return full;
	}

	// Dispatch to channels in parallel
	const dispatches: Promise<void>[] = [];

	if (config.email.enabled) {
		dispatches.push(sendEmail(config.email, full));
	}

	if (config.webhook.enabled) {
		dispatches.push(sendWebhook(config.webhook.url, full));
	}

	if (config.inApp.enabled) {
		storeInApp(full);
	}

	await Promise.allSettled(dispatches);
	return full;
}

/**
 * Store a notification in the in-app JSON store.
 */
function storeInApp(notification: Notification): void {
	const store = getStore();
	store.unshift(notification);
	// Trim to max size
	if (store.length > MAX_STORED_NOTIFICATIONS) {
		store.length = MAX_STORED_NOTIFICATIONS;
	}
	persistStore(store);
}

/**
 * Get recent in-app notifications.
 */
export function getNotifications(limit: number = 20): Notification[] {
	const store = getStore();
	return store.slice(0, limit);
}

/**
 * Get count of unread notifications.
 */
export function getUnreadCount(): number {
	const store = getStore();
	return store.filter((n) => !n.read).length;
}

/**
 * Mark a notification as read.
 */
export function markRead(id: string): boolean {
	const store = getStore();
	const notification = store.find((n) => n.id === id);
	if (!notification) return false;
	notification.read = true;
	persistStore(store);
	return true;
}

/**
 * Mark all notifications as read.
 */
export function markAllRead(): number {
	const store = getStore();
	let count = 0;
	for (const n of store) {
		if (!n.read) {
			n.read = true;
			count++;
		}
	}
	if (count > 0) persistStore(store);
	return count;
}
