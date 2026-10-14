import { goto } from '$app/navigation';
import { api, ApiError, type Me } from './api';

export const session = $state<{ me: Me | null; loaded: boolean }>({ me: null, loaded: false });

export async function loadMe(): Promise<Me | null> {
	try {
		session.me = await api.get<Me>('/api/me');
	} catch (error) {
		if (!(error instanceof ApiError) || error.status !== 401) throw error;
		session.me = null;
	}
	session.loaded = true;
	return session.me;
}

export function homeFor(me: Me): string {
	return me.role === 'student' ? '/' : `/${me.role}`;
}

/** Use at the top of a page: signed-in user with one of these roles, or go elsewhere. */
export async function requireRole(...roles: Me['role'][]): Promise<Me | null> {
	const me = session.loaded ? session.me : await loadMe();
	if (!me) {
		await goto('/login', { replaceState: true });
		return null;
	}
	if (!roles.includes(me.role)) {
		await goto(homeFor(me), { replaceState: true });
		return null;
	}
	return me;
}

export async function logout(): Promise<void> {
	try {
		await api.post('/api/logout');
	} catch {
		// signed out locally either way
	}
	session.me = null;
	// A full page load, not client navigation: nothing from this student's chat stays in
	// memory for the next person on a shared phone.
	window.location.replace('/login');
}

/** Per-user remembered choice (book, chapter) on this device; harmless if storage is blocked. */
export function remember(key: string, value?: string | null): string | null {
	const fullKey = `rm.${session.me?.username ?? 'anon'}.${key}`;
	try {
		if (value === undefined) return localStorage.getItem(fullKey);
		if (value === null) localStorage.removeItem(fullKey);
		else localStorage.setItem(fullKey, value);
	} catch {
		// storage blocked
	}
	return null;
}
