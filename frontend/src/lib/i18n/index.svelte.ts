// UI text in several languages. Adding a language = adding <code>.json here and one line in
// LANGUAGES. A key missing from a language falls back to English, then to the key itself.
// The UI language is also the answer language (one setting for the student).
import en from './en.json';
import ml from './ml.json';

type Dictionary = Record<string, string>;
const dictionaries: Record<string, Dictionary> = { en, ml };

export const LANGUAGES = [
	{ code: 'en', label: 'English' },
	{ code: 'ml', label: 'മലയാളം' }
] as const;
export type Lang = (typeof LANGUAGES)[number]['code'];

const STORAGE_KEY = 'rm.lang';

function initialLanguage(): Lang {
	try {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (saved && saved in dictionaries) return saved as Lang;
	} catch {
		// private mode or storage blocked: fall through to the browser language
	}
	return navigator.language?.toLowerCase().startsWith('ml') ? 'ml' : 'en';
}

let current = $state<Lang>(initialLanguage());
document.documentElement.lang = current;

export function getLang(): Lang {
	return current;
}

export function setLang(lang: Lang): void {
	current = lang;
	document.documentElement.lang = lang;
	try {
		localStorage.setItem(STORAGE_KEY, lang);
	} catch {
		// not remembered, still works for this visit
	}
}

export function t(key: string, values: Record<string, string | number> = {}): string {
	const text = dictionaries[current]?.[key] ?? en[key as keyof typeof en] ?? key;
	return text.replace(/\{(\w+)\}/g, (match, name) =>
		name in values ? String(values[name]) : match
	);
}
