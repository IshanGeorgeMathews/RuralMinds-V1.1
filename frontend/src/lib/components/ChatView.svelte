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
	import Sheet from './Sheet.svelte';

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

	function follow(mode: Mode): void {
		ask(t(`follow.${mode}.question`), { mode, shown: t(`follow.${mode}`), followUp: true });
	}

	function onkeydown(event: KeyboardEvent): void {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			send();
		}
	}

	async function onapprove(turn: (typeof study.turns)[number]): Promise<void> {
		try {
			await approve(turn);
		} catch (error) {
			alert(t(error instanceof ApiError ? error.key : 'error.generic'));
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
	const placeholder = $derived(study.turns.length ? t('ask.followup_placeholder') : t('ask.placeholder'));
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
				<div class="art"><Icon name="sparkle" size={30} /></div>
				<h2>{t('ask.welcome_title')}</h2>
				<p class="muted">{t('ask.welcome_body')}</p>
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

	<form class="composer no-print" onsubmit={(event) => (event.preventDefault(), send())}>
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
		padding: 10px 0;
		background: linear-gradient(var(--bg) 70%, transparent);
	}
	.pill {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 8px;
		min-height: 44px;
		padding: 0 14px;
		border-radius: 999px;
		border: 1px solid var(--line-strong);
		background: var(--surface);
		box-shadow: var(--shadow-sm);
		cursor: pointer;
		color: var(--text);
		text-align: left;
	}
	.pill :global(svg:first-child) {
		color: var(--accent-strong);
	}
	.pill-text {
		flex: 1;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		font-size: 0.92rem;
	}
	.conversation {
		flex: 1;
		display: grid;
		align-content: start;
		gap: 22px;
		padding: 8px 0 24px;
	}
	.welcome {
		display: grid;
		justify-items: center;
		text-align: center;
		gap: 6px;
		padding: 20px 4px;
	}
	.welcome h2 {
		margin: 8px 0 0;
	}
	.welcome p {
		max-width: 36ch;
	}
	.art {
		display: grid;
		place-items: center;
		width: 64px;
		height: 64px;
		border-radius: 22px;
		background: linear-gradient(135deg, var(--accent), var(--accent-strong));
		color: #fff;
		box-shadow: var(--shadow);
	}
	.suggestions {
		display: grid;
		gap: 8px;
		width: 100%;
		max-width: 460px;
		margin-top: 10px;
	}
	.suggestion {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		min-height: 52px;
		padding: 10px 14px;
		border: 1px solid var(--line);
		border-radius: 14px;
		background: var(--surface);
		box-shadow: var(--shadow-sm);
		cursor: pointer;
		text-align: left;
		color: var(--text);
		font-weight: 600;
	}
	.suggestion:hover {
		border-color: var(--accent);
	}
	.suggestion span {
		flex: 1;
	}
	.suggestion :global(svg:first-child) {
		color: var(--accent-strong);
	}
	.composer {
		position: sticky;
		bottom: calc(var(--nav-height) + env(safe-area-inset-bottom));
		padding: 8px 0 10px;
		background: linear-gradient(transparent, var(--bg) 30%);
	}
	@media (min-width: 900px) {
		.composer {
			bottom: 0;
		}
		.chat {
			min-height: calc(100dvh - 58px);
		}
	}
	.box {
		display: flex;
		align-items: flex-end;
		gap: 8px;
		padding: 6px 6px 6px 16px;
		border-radius: 26px;
		border: 1px solid var(--line-strong);
		background: var(--surface);
		box-shadow: var(--shadow);
	}
	.box:focus-within {
		border-color: var(--accent);
	}
	textarea {
		flex: 1;
		border: 0;
		background: transparent;
		resize: none;
		min-height: 44px;
		max-height: 140px;
		padding: 10px 0;
		field-sizing: content;
		font-size: 1rem;
	}
	textarea:focus-visible {
		outline: none;
	}
	.send {
		display: grid;
		place-items: center;
		width: 44px;
		height: 44px;
		border-radius: 50%;
		border: 0;
		background: var(--accent);
		color: var(--on-accent);
		cursor: pointer;
	}
	.send:disabled {
		background: var(--surface-3);
		color: var(--faint);
		cursor: default;
	}
	.send.stop {
		background: var(--text);
		color: var(--bg);
	}
	.hint {
		display: block;
		text-align: center;
		font-size: 0.75rem;
		color: var(--muted);
		margin-top: 6px;
		text-decoration: none;
	}
	.sheet-label {
		margin: 8px 0 6px;
		font-size: 0.8rem;
		font-weight: 750;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
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
		border-radius: 14px;
		background: var(--surface);
		cursor: pointer;
		text-align: left;
		color: var(--text);
	}
	.option[aria-pressed='true'] {
		border-color: var(--accent);
		background: var(--accent-softer);
		font-weight: 700;
	}
	.num {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border-radius: 10px;
		background: var(--surface-2);
		font-weight: 800;
		font-size: 0.85rem;
	}
	.option[aria-pressed='true'] .num {
		background: var(--accent);
		color: var(--on-accent);
	}
</style>
