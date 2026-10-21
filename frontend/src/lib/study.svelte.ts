// Student state shared by the Learn, Ask and chapter screens: the class's books, the chosen
// book/chapter, and the current conversation. In memory only (a shared phone forgets it on
// sign-out or reload); the last book and chapter are remembered on the device.
import { goto } from '$app/navigation';
import { api, ApiError, askStream, type Book, type Citation } from './api.js';
import { prefs } from './prefs.svelte.js';
import { remember } from './session.svelte.js';

export type Mode = 'explain' | 'simpler' | 'example' | 'story' | 'quiz' | 'summary' | 'solve' | 'method';
// "Solve step by step": the calculator's worked lines with the model's sentence under each.
export type SolutionCard = {
	idea: string;
	steps: { line: string; why: string }[];
	try_problem: string;
	answers: string[];
};
export type Notes = {
	document_id: number;
	chapter_no: number;
	chapter_title: string;
	overview: string;
	points: { text: string; page_start: number; page_end: number }[];
	language: string;
	label: string;
};
export type Turn = {
	id: number;
	question: string; // what is sent (a chip sends "<original question> — <instruction>")
	shown: string; // what the bubble shows (a chip shows "Simpler")
	topic: string; // the student's own typed question this conversation is about
	mode: Mode | null;
	documentId: number;
	chapterNo: number | null;
	language: string;
	status: 'searching' | 'queued' | 'writing' | 'done' | 'notes' | 'refused' | 'blocked' | 'error' | 'stopped';
	step?: string; // what the server is doing before any text arrives ("solving")
	queuePosition?: number;
	queueEta?: number | null; // seconds, from the measured answer rate; null = not known yet
	raw: string;
	text: string;
	example: string;
	check: string;
	answers: string;
	citations: Citation[];
	label?: string;
	messageKey?: string;
	gate?: Record<string, any>;
	notes?: Notes;
	card?: SolutionCard;
	mathStatus?: string; // "solved", or why the calculator could not check this problem
	unsolved?: boolean; // the calculator could not take the problem: no model text, only pages
	firstTurn: boolean;
	approved?: boolean;
};

export const study = $state({
	books: [] as Book[],
	loaded: false,
	bookId: 0,
	chapterNo: null as number | null,
	turns: [] as Turn[],
	endpoint: '/api/ask'
});

let controller: AbortController | null = null;
let nextId = 1;

export function currentBook(): Book | undefined {
	return study.books.find((book) => book.id === study.bookId);
}

export function currentChapter() {
	return currentBook()?.chapters.find((chapter) => chapter.no === study.chapterNo);
}

export function isBusy(): boolean {
	return study.turns.some((turn) => ['searching', 'queued', 'writing'].includes(turn.status));
}

export function setBooks(books: Book[], endpoint: string): void {
	study.books = books;
	study.endpoint = endpoint;
	study.loaded = true;
	const saved = Number(remember('book'));
	const book = books.find((b) => b.id === saved) ?? books[0];
	study.bookId = book?.id ?? 0;
	const chapter = Number(remember('chapter'));
	study.chapterNo = book?.chapters.some((c) => c.no === chapter) ? chapter : null;
}

export async function loadCatalog(): Promise<void> {
	const { books } = await api.get<{ books: Book[] }>('/api/catalog');
	setBooks(books, '/api/ask');
}

/** Change where questions are searched. A new place starts a new conversation. */
export function choose(bookId: number, chapterNo: number | null): void {
	if (isBusy()) return;
	if (bookId !== study.bookId || chapterNo !== study.chapterNo) study.turns = [];
	study.bookId = bookId;
	study.chapterNo = chapterNo;
	remember('book', String(bookId));
	remember('chapter', chapterNo === null ? null : String(chapterNo));
}

export function newConversation(): void {
	stop();
	study.turns = [];
}

export function stop(): void {
	controller?.abort();
}

function history() {
	return study.turns
		.filter((turn) => turn.status === 'done')
		.slice(-2)
		.map((turn) => ({ question: turn.question, answer: turn.text }));
}

type AskOptions = { mode?: Mode | null; shown?: string; followUp?: boolean };

/** Ask a question: typed, or from a chip (fixed mode; a follow-up chip keeps the language). */
export async function ask(question: string, options: AskOptions = {}): Promise<void> {
	question = question.trim();
	const book = currentBook();
	if (!question || isBusy() || !book) return;
	const mode = options.mode ?? null;
	const shown = options.shown ?? question;
	const previous = [...study.turns].reverse().find((turn) => ['done', 'notes'].includes(turn.status));
	const answerLanguage =
		options.followUp && previous?.language ? previous.language : prefs.answerLanguage;
	// A chip's own words ("Explain it more simply") name no topic. Sending the student's typed
	// question with it keeps the search on that topic however many chips are tapped in a row.
	const topic = options.followUp && previous ? previous.topic : question;
	if (options.followUp && previous) question = `${topic} — ${question}`;
	study.turns.push({
		id: nextId++,
		question,
		shown,
		topic,
		mode,
		documentId: book.id,
		chapterNo: study.chapterNo,
		language: answerLanguage === 'auto' ? '' : answerLanguage,
		status: 'searching',
		raw: '',
		text: '',
		example: '',
		check: '',
		answers: '',
		citations: [],
		firstTurn: !previous
	});
	const turn = study.turns[study.turns.length - 1];
	const body = {
		question,
		answer_language: answerLanguage,
		mode,
		document_id: book.id,
		chapter_no: study.chapterNo,
		history: history()
	};
	controller = new AbortController();
	try {
		for await (const { event, data } of askStream(study.endpoint, body, controller.signal)) {
			apply(turn, event, data);
		}
		if (controller.signal.aborted && !['done', 'notes'].includes(turn.status)) turn.status = 'stopped';
		else if (['searching', 'queued', 'writing'].includes(turn.status)) fail(turn, 'error.offline');
	} catch (error) {
		if (error instanceof ApiError && error.status === 401) {
			await goto('/login?expired=1', { replaceState: true });
			return;
		}
		fail(turn, error instanceof ApiError ? error.key : 'error.generic');
	} finally {
		controller = null;
	}
}

function fail(turn: Turn, key: string): void {
	turn.status = 'error';
	turn.messageKey = key;
}

function apply(turn: Turn, event: string, data: Record<string, any>): void {
	if (event === 'queued') {
		turn.status = 'queued';
		turn.queuePosition = data.position;
		turn.queueEta = data.eta_s ?? null;
	} else if (event === 'progress') {
		turn.status = 'searching';
		turn.step = data.step;
	} else if (event === 'token') {
		turn.status = 'writing';
		turn.raw += data.text;
	} else if (event === 'done') {
		Object.assign(turn, {
			status: 'done',
			text: data.text ?? '',
			example: data.example ?? '',
			check: data.check ?? '',
			answers: data.answers ?? '',
			citations: data.citations ?? [],
			label: data.label,
			gate: data.gate,
			language: data.language ?? turn.language,
			mode: data.mode ?? turn.mode,
			card: data.card ?? undefined,
			mathStatus: data.math_status ?? undefined,
			unsolved: data.unsolved ?? false
		});
	} else if (event === 'notes') {
		turn.status = 'notes';
		turn.notes = data as Notes;
		turn.label = data.label;
		turn.language = data.language;
	} else {
		// refused | blocked | busy | error: the whole card is replaced, nothing unchecked stays
		turn.status = event === 'refused' ? 'refused' : event === 'blocked' ? 'blocked' : 'error';
		turn.raw = '';
		turn.messageKey = data.message_key ?? 'error.generic';
		turn.gate = data.gate;
	}
}

export async function approve(turn: Turn): Promise<void> {
	await api.post('/api/teacher/approve', {
		question: turn.question,
		language: turn.language || 'en',
		document_id: turn.documentId,
		chapter_no: turn.chapterNo,
		text: turn.text,
		example: turn.example,
		check: turn.check,
		answers: turn.answers,
		citations: turn.citations
	});
	turn.approved = true;
}
