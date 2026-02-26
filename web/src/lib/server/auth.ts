import * as argon2 from 'argon2';
import jwt from 'jsonwebtoken';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs';
import { dirname } from 'path';

// ----- Constants -----

const JWT_SECRET = process.env.JWT_SECRET || 'nettap-dev-secret-change-in-production';
const TOKEN_EXPIRY = '24h';
const DATA_DIR = process.env.DATA_DIR || '/var/lib/nettap-web';
const USERS_FILE = `${DATA_DIR}/users.json`;

// ----- Types -----

export interface User {
	username: string;
	passwordHash: string;
	role: string;
	createdAt: string;
	updatedAt: string;
}

export interface TokenPayload {
	username: string;
	role: string;
}

interface UsersStore {
	users: User[];
}

// ----- Password Hashing -----

export async function hashPassword(password: string): Promise<string> {
	return argon2.hash(password, {
		type: argon2.argon2id,
		memoryCost: 65536,
		timeCost: 3,
		parallelism: 4,
	});
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
	try {
		return await argon2.verify(hash, password);
	} catch {
		return false;
	}
}

// ----- JWT -----

export function generateToken(payload: TokenPayload): string {
	return jwt.sign(payload, JWT_SECRET, { expiresIn: TOKEN_EXPIRY });
}

export function verifyToken(token: string): TokenPayload | null {
	try {
		const decoded = jwt.verify(token, JWT_SECRET) as jwt.JwtPayload & TokenPayload;
		return { username: decoded.username, role: decoded.role };
	} catch {
		return null;
	}
}

// ----- User Storage -----

function ensureDataDir(): void {
	if (!existsSync(DATA_DIR)) {
		try {
			mkdirSync(DATA_DIR, { recursive: true });
		} catch {
			// In development, DATA_DIR might not be writable; silently continue
		}
	}
}

function readUsers(): UsersStore {
	try {
		const data = readFileSync(USERS_FILE, 'utf-8');
		return JSON.parse(data) as UsersStore;
	} catch {
		return { users: [] };
	}
}

function writeUsers(store: UsersStore): void {
	ensureDataDir();
	const dir = dirname(USERS_FILE);
	if (!existsSync(dir)) {
		mkdirSync(dir, { recursive: true });
	}
	writeFileSync(USERS_FILE, JSON.stringify(store, null, 2), 'utf-8');
}

export function getUser(username: string): User | undefined {
	const store = readUsers();
	return store.users.find((u) => u.username === username);
}

export async function createUser(
	username: string,
	password: string,
	role: string = 'admin'
): Promise<User> {
	const store = readUsers();

	if (store.users.find((u) => u.username === username)) {
		throw new Error(`User "${username}" already exists`);
	}

	const now = new Date().toISOString();
	const user: User = {
		username,
		passwordHash: await hashPassword(password),
		role,
		createdAt: now,
		updatedAt: now,
	};

	store.users.push(user);
	writeUsers(store);
	return user;
}

export async function updatePassword(username: string, newPassword: string): Promise<void> {
	const store = readUsers();
	const user = store.users.find((u) => u.username === username);

	if (!user) {
		throw new Error(`User "${username}" not found`);
	}

	user.passwordHash = await hashPassword(newPassword);
	user.updatedAt = new Date().toISOString();
	writeUsers(store);
}

export function hasUsers(): boolean {
	const store = readUsers();
	return store.users.length > 0;
}
