// A tiny, safe markdown subset for answers: paragraphs, "- " and "1. " lists, **bold**, and
// [S1] source markers turned into small citation buttons. Everything is HTML-escaped first,
// so text from the model can never inject markup.

const ESCAPES: Record<string, string> = {
	'&': '&amp;',
	'<': '&lt;',
	'>': '&gt;',
	'"': '&quot;',
	"'": '&#39;'
};

export function escapeHtml(text: string): string {
	return text.replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

function inline(text: string, withCitations: boolean): string {
	let html = escapeHtml(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
	html = html.replace(/\[S(\d+)\]/g, (_, number) =>
		withCitations ? `<button type="button" class="cite" data-cite="${number}">${number}</button>` : ''
	);
	return html.replace(/\s+([.,;:!?])/g, '$1');
}

const BULLET = /^\s*[-*•]\s+/;
const NUMBERED = /^\s*\d+[.)]\s+/;

export function renderMarkdown(text: string, withCitations = true): string {
	const blocks: string[] = [];
	let list: { kind: 'ul' | 'ol'; items: string[] } | null = null;
	const flush = () => {
		if (list) blocks.push(`<${list.kind}>${list.items.map((item) => `<li>${item}</li>`).join('')}</${list.kind}>`);
		list = null;
	};
	for (const raw of text.split('\n')) {
		const line = raw.trimEnd();
		const kind = BULLET.test(line) ? 'ul' : NUMBERED.test(line) ? 'ol' : null;
		if (kind) {
			if (!list || list.kind !== kind) {
				flush();
				list = { kind, items: [] };
			}
			list.items.push(inline(line.replace(kind === 'ul' ? BULLET : NUMBERED, ''), withCitations));
		} else if (line.trim()) {
			flush();
			blocks.push(`<p>${inline(line.trim(), withCitations)}</p>`);
		} else {
			flush();
		}
	}
	flush();
	return blocks.join('');
}

/** Split live (still streaming) text at the same labels the server uses. */
const LABEL =
	/^[ \t]*[*_#]*[ \t]*(EXAMPLE|ഉദാഹരണം|CHECK|Check yourself|സ്വയം പരിശോധിക്കാം|ANSWERS|ഉത്തരങ്ങൾ)[ \t]*[*_]*[ \t]*[:：][*_]*/gim;
const KIND: Record<string, 'example' | 'check' | 'answers'> = {
	example: 'example',
	'ഉദാഹരണം': 'example',
	check: 'check',
	'check yourself': 'check',
	'സ്വയം പരിശോധിക്കാം': 'check',
	answers: 'answers',
	'ഉത്തരങ്ങൾ': 'answers'
};

export type Sections = { text: string; example: string; check: string; answers: string };

export function splitSections(raw: string): Sections {
	const sections: Sections = { text: '', example: '', check: '', answers: '' };
	const matches = [...raw.matchAll(LABEL)];
	sections.text = (matches.length ? raw.slice(0, matches[0].index) : raw).trim();
	matches.forEach((match, index) => {
		const end = index + 1 < matches.length ? matches[index + 1].index : raw.length;
		const kind = KIND[match[1].toLowerCase()];
		const body = raw.slice(match.index! + match[0].length, end).trim();
		sections[kind] = sections[kind] ? `${sections[kind]}\n${body}` : body;
	});
	return sections;
}
