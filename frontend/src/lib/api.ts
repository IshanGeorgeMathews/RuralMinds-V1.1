// Talking to the school server. Every error becomes an ApiError whose `key` is an i18n key,
// so the screen can show it in the student's language.

export class ApiError extends Error {
	constructor(
		public status: number,
		public key: string,
		public keys: string[] = [key]
	) {
		super(key);
	}
}

async function toError(response: Response): Promise<ApiError> {
	try {
		const body = await response.json();
		const detail = body?.detail;
		if (typeof detail === 'string') return new ApiError(response.status, detail);
		if (Array.isArray(detail) && detail.every((item) => typeof item === 'string')) {
			return new ApiError(response.status, detail[0] ?? 'error.invalid', detail);
		}
		return new ApiError(response.status, 'error.invalid');
	} catch {
		return new ApiError(response.status, 'error.generic');
	}
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
	let response: Response;
	try {
		response = await fetch(path, {
			method,
			headers: body === undefined ? {} : { 'content-type': 'application/json' },
			body: body === undefined ? undefined : JSON.stringify(body),
			credentials: 'same-origin'
		});
	} catch {
		throw new ApiError(0, 'error.offline');
	}
	if (!response.ok) throw await toError(response);
	return (response.status === 204 ? null : await response.json()) as T;
}

export const api = {
	get: <T>(path: string) => send<T>('GET', path),
	post: <T>(path: string, body: unknown = {}) => send<T>('POST', path, body),
	del: <T>(path: string) => send<T>('DELETE', path)
};

export type AnswerEvent = { event: string; data: Record<string, any> };

/** POST a question and yield server-sent events as they arrive (EventSource cannot POST). */
export async function* askStream(
	path: string,
	body: unknown,
	signal: AbortSignal
): AsyncGenerator<AnswerEvent> {
	let response: Response;
	try {
		response = await fetch(path, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify(body),
			credentials: 'same-origin',
			signal
		});
	} catch (error) {
		if (signal.aborted) return;
		throw new ApiError(0, 'error.offline');
	}
	if (!response.ok || !response.body) throw await toError(response);
	const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
	let buffer = '';
	try {
		while (true) {
			const { value, done } = await reader.read();
			if (done) break;
			buffer += value;
			let end;
			while ((end = buffer.indexOf('\n\n')) >= 0) {
				const block = buffer.slice(0, end);
				buffer = buffer.slice(end + 2);
				const parsed = parseBlock(block);
				if (parsed) yield parsed;
			}
		}
	} catch (error) {
		if (signal.aborted) return;
		throw new ApiError(0, 'error.offline');
	}
}

function parseBlock(block: string): AnswerEvent | null {
	let event = 'message';
	const data: string[] = [];
	for (const line of block.split('\n')) {
		if (line.startsWith('event:')) event = line.slice(6).trim();
		else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
	}
	if (!data.length) return null;
	return { event, data: JSON.parse(data.join('\n')) };
}

/** Upload with a progress bar (fetch cannot report upload progress; XHR can). */
export function uploadFile(
	path: string,
	file: File,
	onProgress: (fraction: number) => void
): Promise<any> {
	return new Promise((resolve, reject) => {
		const request = new XMLHttpRequest();
		request.open('PUT', path);
		request.setRequestHeader('content-type', 'application/pdf');
		request.upload.onprogress = (event) => {
			if (event.lengthComputable) onProgress(event.loaded / event.total);
		};
		request.onload = () => {
			let body: any = null;
			try {
				body = JSON.parse(request.responseText);
			} catch {
				// not JSON
			}
			if (request.status >= 200 && request.status < 300) resolve(body);
			else reject(new ApiError(request.status, body?.detail ?? 'error.generic'));
		};
		request.onerror = () => reject(new ApiError(0, 'error.offline'));
		request.send(file);
	});
}

export type Me = {
	username: string;
	role: 'student' | 'teacher' | 'admin';
	class: { id: number; grade: number; section: string; medium: string } | null;
};

export type Chapter = {
	no: number;
	title: string;
	page: number;
	last_page?: number | null;
	notes?: Record<string, string>; // language -> draft | approved
};
export type Book = {
	id: number;
	title: string;
	subject: string;
	medium: string;
	grade: number;
	status?: string;
	chapters: Chapter[];
};

export type Citation = {
	marker: string;
	book_id: string;
	chapter_no: number;
	chapter_title: string;
	page_start: number;
	page_end: number;
};
