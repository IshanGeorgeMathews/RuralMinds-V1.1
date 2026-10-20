<script lang="ts">
	import { tick } from 'svelte';
	import { ApiError } from '#lib/api.js';
	import { t } from '#lib/i18n/index.svelte.js';
	import { prefs } from '#lib/prefs.svelte.js';
	import {
		approve,
		ask,
		choose,
		currentBook,
		currentChapter,
		isBusy,
		newConversation,
		stop,
		study,
		type Mode
	} from '#lib/study.svelte.js';
	import AnswerCard from './AnswerCard.svelte';
	import Icon from './Icon.svelte';
	import Logo from './Logo.svelte';
	import RevisionChips from './RevisionChips.svelte';
	import Sheet from './Sheet.svelte';
	import { toast } from '#lib/feedback.svelte.js';

	let { teacherMode = false }: { teacherMode?: boolean } = $props();

	let question = $state('');
	let picking = $state(false);
	let input: HTMLTextAreaElement;
	let end: HTMLDivElement;

	const book = $derived(currentBook());
	const chapter = $derived(currentChapter());
	const busy = $derived(isBusy());

	// Keep the newest text in view while an answer streams in.
	$effect(() => {
		const last = study.turns[study.turns.length - 1];
		void last?.raw;
		void last?.status;
		tick().then(() => end?.scrollIntoView({ block: 'end', behavior: 'smooth' }));
	});

	function send(text = question, mode: Mode | null = null): void {
		if (!text.trim() || busy) return;
		question = '';
		ask(text, { mode });
		input?.blur();
	}

	// "Solve step by step": only for books with calculations. It applies to typed problems only
	// (a suggestion chip keeps its own mode) and stays on for the next problem until turned off.
	let solveOn = $state(false);
	const canSolve = $derived(['science', 'maths'].includes(book?.subject ?? ''));

	function sendTyped(): void {
		send(question, solveOn && canSolve ? 'solve' : null);
	}

	function follow(mode: Mode): void {
		ask(t(`follow.${mode}.question`), { mode, shown: t(`follow.${mode}`), followUp: true });
	}

	function onkeydown(event: KeyboardEvent): void {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			sendTyped();
		}
	}

	async function onapprove(turn: (typeof study.turns)[number]): Promise<void> {
		try {
			await approve(turn);
		} catch (error) {
			toast(t(error instanceof ApiError ? error.key : 'error.generic'), 'error');
		}
	}

	const suggestions = $derived(
		chapter
			? [
					{ mode: 'summary' as Mode, icon: 'list', text: t('suggest.summary', { n: chapter.no }) },
					{ mode: 'quiz' as Mode, icon: 'quiz', text: t('suggest.quiz') },
					{ mode: null, icon: 'sparkle', text: t('suggest.about', { title: chapter.title }) }
				]
			: []
	);
	const placeholder = $derived(
		solveOn && canSolve
			? t('solve.placeholder')
			: study.turns.length
				? t('ask.followup_placeholder')
				: t('ask.placeholder')
	);
	const languageNote = $derived(
		prefs.answerLanguage === 'auto' ? t('ask.answer_auto') : t('ask.answer_in', { language: t(`medium.${prefs.answerLanguage}`) })
	);
</script>

<section class="chat">
	<div class="context no-print">
		<button class="pill" onclick={() => (picking = true)} disabled={busy}>
			<Icon name="book" size={18} />
			<span class="pill-text">
				{#if chapter}
					<strong>{t('ask.chapter_short', { n: chapter.no })}</strong> · {chapter.title}
				{:else}
					<strong>{t('ask.whole_book')}</strong> · {book?.title ?? ''}
				{/if}
			</span>
			<Icon name="chevronDown" size={18} />
		</button>
		{#if study.turns.length && !busy}
			<button class="btn ghost small" onclick={newConversation}><Icon name="plus" size={16} />{t('ask.new')}</button>
		{/if}
	</div>

	<div class="conversation" aria-live="polite">
		{#if study.turns.length === 0}
			<div class="welcome">
				<Logo size={56} />
				<h2>{t('ask.welcome_title')}</h2>
				<p class="muted">{t('ask.welcome_body')}</p>
				{#if !teacherMode && study.bookId}<RevisionChips bookId={study.bookId} chapterNo={study.chapterNo} />{/if}
				<div class="suggestions">
					{#if !chapter}
						<button class="suggestion" onclick={() => (picking = true)}>
							<Icon name="book" size={18} /><span>{t('suggest.pick')}</span><Icon name="chevronRight" size={16} />
						</button>
					{/if}
					{#each suggestions as suggestion (suggestion.text)}
						<button class="suggestion" onclick={() => send(suggestion.text, suggestion.mode)}>
							<Icon name={suggestion.icon} size={18} /><span>{suggestion.text}</span><Icon name="chevronRight" size={16} />
						</button>
					{/each}
				</div>
			</div>
		{/if}
		{#each study.turns as turn, index (turn.id)}
			<AnswerCard {turn} {teacherMode} last={index === study.turns.length - 1} onfollow={follow} {onapprove} />
		{/each}
		<div bind:this={end}></div>
	</div>

	<form class="composer no-print" onsubmit={(event) => (event.preventDefault(), sendTyped())}>
		{#if canSolve}
			<button type="button" class="solve-toggle" aria-pressed={solveOn} onclick={() => (solveOn = !solveOn)}>
				<Icon name={solveOn ? 'check' : 'pencil'} size={16} />{t('solve.toggle')}
			</button>
		{/if}
		<div class="box">
			<textarea
				bind:this={input}
				bind:value={question}
				{onkeydown}
				rows="1"
				maxlength="500"
				{placeholder}
				aria-label={t('ask.placeholder')}
			></textarea>
			{#if busy}
				<button type="button" class="send stop" onclick={stop} aria-label={t('ask.stop')}><Icon name="stop" /></button>
			{:else}
				<button class="send" disabled={!question.trim()} aria-label={t('ask.send')}><Icon name="send" /></button>
			{/if}
		</div>
		<a class="hint" href="/settings">{languageNote}</a>
	</form>
</section>

{#if picking && book}
	<Sheet title={t('ask.where')} onclose={() => (picking = false)}>
		{#if study.books.length > 1}
			<p class="sheet-label">{t('ask.book')}</p>
			<div class="options">
				{#each study.books as option (option.id)}
					<button class="option" aria-pressed={option.id === study.bookId} onclick={() => choose(option.id, null)}>
						<Icon name="book" size={18} /><span class="grow">{option.title}</span>
						{#if teacherMode && option.status && option.status !== 'published'}<span class="badge warn">{t('teacher.status.ready')}</span>{/if}
					</button>
				{/each}
			</div>
		{/if}
		<p class="sheet-label">{t('ask.chapter')}</p>
		<div class="options">
			<button class="option" aria-pressed={study.chapterNo === null} onclick={() => ((picking = false), choose(study.bookId, null))}>
				<span class="num">∗</span><span class="grow">{t('ask.whole_book')}</span>
			</button>
			{#each book.chapters as option (option.no)}
				<button class="option" aria-pressed={study.chapterNo === option.no} onclick={() => ((picking = false), choose(study.bookId, option.no))}>
					<span class="num">{option.no}</span><span class="grow">{option.title}</span>
				</button>
			{/each}
		</div>
	</Sheet>
{/if}

<style>
	.chat {
		display: flex;
		flex-direction: column;
		min-height: calc(100dvh - var(--nav-height) - 58px);
	}
	.context {
		position: sticky;
		top: 58px;
		z-index: 5;
		display: flex;
		gap: 8px;
		align-items: center;
		padding: 12px 0 10px;
		background: linear-gradient(var(--bg) 75%, transparent);
	}
	.pill {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 8px;
		min-height: 42px;
		padding: 0 12px 0 14px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: var(--surface);
		box-shadow: var(--shadow-xs);
		cursor: pointer;
		color: var(--text);
		text-align: left;
		transition: border-color 0.15s;
	}
	.pill:hover:not(:disabled) {
		border-color: var(--line-strong);
	}
	.pill :global(svg:first-child) {
		color: var(--accent-strong);
	}
	.pill :global(svg:last-child) {
		color: var(--faint);
	}
	.pill-text {
		flex: 1;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		font-size: 0.9rem;
		color: var(--muted);
	}
	.pill-text strong {
		color: var(--text);
		font-weight: 650;
	}
	.conversation {
		flex: 1;
		display: grid;
		align-content: start;
		gap: 28px;
		padding: 8px 0 24px;
	}
	.welcome {
		display: grid;
		justify-items: center;
		text-align: center;
		gap: 6px;
		padding: 28px 4px 12px;
	}
	.welcome h2 {
		margin: 14px 0 0;
		font-size: 1.45rem;
		letter-spacing: -0.025em;
	}
	.welcome p {
		max-width: 40ch;
	}
	.suggestions {
		display: grid;
		gap: 8px;
		width: 100%;
		max-width: 560px;
		margin-top: 14px;
	}
	@media (min-width: 700px) {
		.suggestions {
			grid-template-columns: 1fr 1fr;
		}
		.suggestions > :only-child,
		.suggestions > :first-child:nth-last-child(odd) {
			grid-column: 1 / -1;
		}
	}
	.suggestion {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		min-height: 56px;
		padding: 10px 14px;
		border: 1px solid var(--line);
		border-radius: 14px;
		background: var(--surface);
		box-shadow: var(--shadow-xs);
		cursor: pointer;
		text-align: left;
		color: var(--text);
		font-weight: 550;
		font-size: 0.94rem;
		transition:
			border-color 0.15s,
			background 0.15s;
	}
	.suggestion:hover {
		border-color: var(--line-strong);
		background: var(--surface-2);
	}
	.suggestion span {
		flex: 1;
	}
	.suggestion :global(svg:first-child) {
		color: var(--accent-strong);
	}
	.suggestion :global(svg:last-child) {
		color: var(--faint);
	}
	.composer {
		position: sticky;
		bottom: calc(var(--nav-height) + env(safe-area-inset-bottom));
		padding: 10px 0 10px;
		background: linear-gradient(transparent, var(--bg) 35%);
	}
	@media (min-width: 900px) {
		.composer {
			bottom: 0;
			padding-bottom: 16px;
		}
		.chat {
			min-height: calc(100dvh - 58px);
		}
	}
	.box {
		display: flex;
		align-items: flex-end;
		gap: 8px;
		padding: 7px 7px 7px 18px;
		border-radius: 24px;
		border: 1px solid var(--line-strong);
		background: var(--surface);
		box-shadow: var(--shadow);
		transition:
			border-color 0.15s,
			box-shadow 0.15s;
	}
	.box:focus-within {
		border-color: var(--accent);
		box-shadow: var(--shadow), var(--ring);
	}
	textarea {
		flex: 1;
		border: 0;
		background: transparent;
		box-shadow: none;
		resize: none;
		min-height: 44px;
		max-height: 140px;
		padding: 10px 0;
		field-sizing: content;
		font-size: 1rem;
	}
	textarea:focus-visible {
		outline: none;
		box-shadow: none;
	}
	.send {
		display: grid;
		place-items: center;
		width: 44px;
		height: 44px;
		border-radius: 50%;
		border: 0;
		background: var(--primary);
		color: var(--on-primary);
		cursor: pointer;
		transition:
			background 0.15s,
			transform 0.05s;
	}
	.send:hover:not(:disabled) {
		background: var(--primary-hover);
	}
	.send:active:not(:disabled) {
		transform: scale(0.95);
	}
	.send:disabled {
		background: var(--surface-3);
		color: var(--faint);
		cursor: default;
	}
	.send.stop {
		background: var(--surface-2);
		color: var(--text);
		border: 1px solid var(--line-strong);
	}
	.solve-toggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-height: 36px;
		margin: 0 0 8px 4px;
		padding: 0 14px;
		border-radius: 999px;
		border: 1px solid var(--line-strong);
		background: var(--surface);
		color: var(--text);
		font-size: 0.86rem;
		font-weight: 600;
		cursor: pointer;
	}
	.solve-toggle :global(svg) {
		color: var(--accent-strong);
	}
	.solve-toggle[aria-pressed='true'] {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--on-accent);
	}
	.solve-toggle[aria-pressed='true'] :global(svg) {
		color: var(--on-accent);
	}
	.hint {
		display: block;
		text-align: center;
		font-size: 0.74rem;
		color: var(--faint);
		margin-top: 8px;
		text-decoration: none;
	}
	.hint:hover {
		color: var(--muted);
	}
	.sheet-label {
		margin: 10px 0 8px;
		font-size: 0.74rem;
		font-weight: 650;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.07em;
	}
	.options {
		display: grid;
		gap: 6px;
	}
	.option {
		display: flex;
		align-items: center;
		gap: 12px;
		min-height: 52px;
		padding: 8px 12px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--surface);
		cursor: pointer;
		text-align: left;
		color: var(--text);
		transition:
			border-color 0.15s,
			background 0.15s;
	}
	.option:hover {
		background: var(--surface-2);
	}
	.option[aria-pressed='true'] {
		border-color: var(--accent);
		background: var(--accent-softer);
		font-weight: 650;
	}
	.num {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border-radius: 8px;
		background: var(--surface-2);
		border: 1px solid var(--line);
		font-weight: 700;
		font-size: 0.85rem;
		font-variant-numeric: tabular-nums;
	}
	.option[aria-pressed='true'] .num {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--on-accent);
	}
</style>
