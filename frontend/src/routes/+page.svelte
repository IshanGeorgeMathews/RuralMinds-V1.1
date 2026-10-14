<script lang="ts">
	import { goto } from '$app/navigation';
	import Icon from '#lib/components/Icon.svelte';
	import StudentGate from '#lib/components/StudentGate.svelte';
	import StudentShell from '#lib/components/StudentShell.svelte';
	import { t } from '#lib/i18n/index.svelte.js';
	import { session } from '#lib/session.svelte.js';
	import { choose, currentBook, study } from '#lib/study.svelte.js';

	const book = $derived(currentBook());

	function askAbout(chapter: number | null): void {
		choose(study.bookId, chapter);
		goto('/ask');
	}
	const pages = (first: number, last: number | null) => (last && last > first ? `${first}–${last}` : `${first}`);
</script>

<StudentShell>
	<StudentGate>
		{#if book}
			<header class="hero">
				<div class="wrap">
					<p class="hello">{t('learn.hello', { name: session.me?.username ?? '' })}</p>
					<h1>{t('learn.title')}</h1>
					<div class="book-card">
						<div class="cover" aria-hidden="true"><Icon name="book" size={28} /></div>
						<div class="grow">
							<p class="book-title">{book.title}</p>
							<p class="book-meta">
								{t(`subject.${book.subject}`)} · {t('learn.chapters', { n: book.chapters.length })}
							</p>
						</div>
						{#if study.books.length > 1}
							<select
								class="book-switch"
								value={study.bookId}
								onchange={(event) => choose(Number(event.currentTarget.value), null)}
								aria-label={t('ask.book')}
							>
								{#each study.books as option (option.id)}<option value={option.id}>{option.title}</option>{/each}
							</select>
						{/if}
					</div>
					<button class="ask-box" onclick={() => askAbout(null)}>
						<Icon name="sparkle" size={20} />
						<span>{t('learn.ask_anything')}</span>
					</button>
				</div>
			</header>

			<main class="wrap chapters">
				<h2>{t('learn.chapters_title')}</h2>
				{#each book.chapters as chapter (chapter.no)}
					{@const hasNotes = Object.keys(chapter.notes ?? {}).length > 0}
					<article class="chapter">
						<a class="chapter-main" href={`/learn/${book.id}/${chapter.no}`}>
							<span class="num">{chapter.no}</span>
							<span class="grow">
								<span class="chapter-title">{chapter.title}</span>
								<span class="chapter-meta">{t('learn.pages', { pages: pages(chapter.page, chapter.last_page ?? null) })}</span>
							</span>
							<Icon name="chevronRight" size={20} />
						</a>
						<div class="chapter-actions">
							<a class="chip soft" href={`/learn/${book.id}/${chapter.no}`}>
								<Icon name="list" size={16} />{hasNotes ? t('learn.notes') : t('learn.notes_soon')}
							</a>
							<button class="chip" onclick={() => askAbout(chapter.no)}>
								<Icon name="chat" size={16} />{t('learn.ask')}
							</button>
						</div>
					</article>
				{/each}
			</main>
		{/if}
	</StudentGate>
</StudentShell>

<style>
	.hero {
		background:
			radial-gradient(120% 120% at 100% 0%, color-mix(in srgb, var(--accent) 22%, transparent), transparent 60%),
			linear-gradient(180deg, var(--bg-tint), var(--bg));
		padding: 22px 0 18px;
		border-bottom: 1px solid var(--line);
	}
	.hello {
		margin: 0;
		color: var(--muted);
		font-weight: 600;
	}
	.hero h1 {
		margin: 2px 0 14px;
	}
	.book-card {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 14px;
		border-radius: var(--radius-lg);
		background: var(--surface);
		border: 1px solid var(--line);
		box-shadow: var(--shadow);
		flex-wrap: wrap;
	}
	.cover {
		display: grid;
		place-items: center;
		width: 54px;
		height: 66px;
		border-radius: 10px 14px 14px 10px;
		background: linear-gradient(135deg, var(--accent), var(--accent-strong));
		color: #fff;
		box-shadow: inset 6px 0 0 rgb(0 0 0 / 0.15);
	}
	.book-title {
		margin: 0;
		font-weight: 750;
		font-size: 1.05rem;
	}
	.book-meta {
		margin: 2px 0 0;
		color: var(--muted);
		font-size: 0.88rem;
	}
	.book-switch {
		width: auto;
		min-height: 38px;
		flex: 1 1 100%;
	}
	.ask-box {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		margin-top: 12px;
		min-height: 54px;
		padding: 0 18px;
		border-radius: 999px;
		border: 1px solid var(--line-strong);
		background: var(--surface);
		color: var(--muted);
		font-size: 1rem;
		text-align: left;
		cursor: pointer;
		box-shadow: var(--shadow-sm);
	}
	.ask-box :global(svg) {
		color: var(--accent-strong);
	}
	.ask-box:hover {
		border-color: var(--accent);
	}
	.chapters {
		display: grid;
		gap: 10px;
		padding-top: 18px;
		padding-bottom: 24px;
	}
	.chapters h2 {
		margin: 0 0 2px;
		font-size: 1.05rem;
		color: var(--muted);
	}
	.chapter {
		background: var(--surface);
		border: 1px solid var(--line);
		border-radius: var(--radius);
		box-shadow: var(--shadow-sm);
		overflow: hidden;
	}
	.chapter-main {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 14px 14px 8px;
		color: var(--text);
		text-decoration: none;
	}
	.chapter-main :global(svg) {
		color: var(--faint);
	}
	.num {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		border-radius: 12px;
		background: var(--accent-soft);
		color: var(--accent-strong);
		font-weight: 800;
		flex-shrink: 0;
	}
	.chapter-title {
		display: block;
		font-weight: 700;
	}
	.chapter-meta {
		display: block;
		color: var(--muted);
		font-size: 0.82rem;
	}
	.chapter-actions {
		display: flex;
		gap: 8px;
		padding: 0 14px 12px 66px;
		flex-wrap: wrap;
	}
	.chapter-actions .chip {
		text-decoration: none;
		min-height: 34px;
		font-size: 0.85rem;
	}
</style>
