// Per-device preferences (Settings). Kept in localStorage only: nothing about the student
// is sent to the server except the answer language, with each question.

export type AnswerLanguage = 'auto' | 'en' | 'ml';
export type TextSize = 'md' | 'lg' | 'xl';
export type Theme = 'system' | 'light' | 'dark';

type Prefs = { answerLanguage: AnswerLanguage; textSize: TextSize; theme: Theme };
const KEY = 'rm.prefs';
const DEFAULTS: Prefs = { answerLanguage: 'auto', textSize: 'md', theme: 'system' };

function load(): Prefs {
	try {
		return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) ?? '{}') };
	} catch {
		return { ...DEFAULTS };
	}
}

export const prefs = $state<Prefs>(load());

export function savePrefs(): void {
	try {
		localStorage.setItem(KEY, JSON.stringify(prefs));
	} catch {
		// storage blocked: settings last for this visit only
	}
	applyPrefs();
}

const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');

export function applyPrefs(): void {
	const root = document.documentElement;
	root.dataset.size = prefs.textSize;
	const dark = prefs.theme === 'dark' || (prefs.theme === 'system' && darkQuery.matches);
	root.dataset.theme = dark ? 'dark' : 'light';
	document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0b0f0e' : '#f7f8f7');
}

darkQuery.addEventListener('change', applyPrefs);
applyPrefs();
