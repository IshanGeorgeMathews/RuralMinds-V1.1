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
					<p class="eyebrow">{t('learn.hello', { name: session.me?.username ?? '' })}</p>
					<h1>{t('learn.title')}</h1>

					<button class="ask-box" onclick={() => askAbout(null)}>
						<span class="ask-icon"><Icon name="sparkle" size={20} /></span>
						<span class="grow">{t('learn.ask_anything')}</span>
						<span class="ask-go"><Icon name="send" size={18} /></span>
					</button>

					<div class="book-card">
						<div class="cover" aria-hidden="true"><Icon name="book" size={24} /></div>
						<div class="grow">
							<p class="eyebrow">{t('student.book')}</p>
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
				</div>
			</header>

			<main class="wrap chapters">
				<div class="section-head">
					<h2>{t('learn.chapters_title')}</h2>
					<span class="muted small tabular">{t('learn.chapters', { n: book.chapters.length })}</span>
				</div>
				<ol class="list-group">
					{#each book.chapters as chapter (chapter.no)}
						{@const hasNotes = Object.keys(chapter.notes ?? {}).length > 0}
						<li class="chapter">
							<a class="chapter-main" href={`/learn/${book.id}/${chapter.no}`}>
								<span class="num tabular">{chapter.no}</span>
								<span class="grow">
									<span class="chapter-title">{chapter.title}</span>
									<span class="chapter-meta tabular">{t('learn.pages', { pages: pages(chapter.page, chapter.last_page ?? null) })}</span>
								</span>
								<Icon name="chevronRight" size={20} />
							</a>
							<div class="chapter-actions">
								<a class="mini" class:ready={hasNotes} href={`/learn/${book.id}/${chapter.no}`}>
									<span class="status-dot" class:idle={!hasNotes}></span>{hasNotes ? t('learn.notes') : t('learn.notes_soon')}
								</a>
								<button class="mini" onclick={() => askAbout(chapter.no)}>
									<Icon name="chat" size={15} />{t('learn.ask')}
								</button>
							</div>
						</li>
					{/each}
				</ol>
			</main>
		{/if}
	</StudentGate>
</StudentShell>

<style>
	.hero {
		position: relative;
		padding: 28px 0 22px;
		background:
			radial-gradient(80% 90% at 100% 0%, color-mix(in srgb, var(--accent) 14%, transparent), transparent 65%),
			linear-gradient(180deg, var(--bg-tint), var(--bg));
	}
	.hero h1 {
		margin: 4px 0 18px;
		font-size: 1.9rem;
		max-width: 18ch;
	}
	.ask-box {
		display: flex;
		align-items: center;
		gap: 12px;
		width: 100%;
		min-height: 64px;
		padding: 8px 8px 8px 10px;
		border-radius: 18px;
		border: 1px solid var(--line-strong);
		background: var(--surface);
		color: var(--muted);
		font-size: 1rem;
		text-align: left;
		cursor: pointer;
		box-shadow: var(--shadow);
		transition:
			border-color 0.15s,
			box-shadow 0.15s;
	}
	.ask-box:hover {
		border-color: var(--accent);
		box-shadow: var(--shadow), var(--ring);
	}
	.ask-icon {
		display: grid;
		place-items: center;
		width: 44px;
		height: 44px;
		border-radius: 12px;
		background: var(--accent-softer);
		color: var(--accent-strong);
		flex-shrink: 0;
	}
	.ask-go {
		display: grid;
		place-items: center;
		width: 44px;
		height: 44px;
		border-radius: 50%;
		background: var(--primary);
		color: var(--on-primary);
		flex-shrink: 0;
	}
	.book-card {
		display: flex;
		align-items: center;
		gap: 14px;
		margin-top: 14px;
		padding: 14px;
		border-radius: 18px;
		background: color-mix(in srgb, var(--surface) 70%, transparent);
		border: 1px solid var(--line);
		flex-wrap: wrap;
	}
	.cover {
		display: grid;
		place-items: center;
		width: 48px;
		height: 62px;
		border-radius: 4px 10px 10px 4px;
		background:
			linear-gradient(90deg, rgb(0 0 0 / 0.22) 0 5px, transparent 5px),
			linear-gradient(150deg, #13897c, #0a4f48);
		color: rgb(255 255 255 / 0.92);
		box-shadow: var(--shadow-sm);
		flex-shrink: 0;
	}
	.book-title {
		overflow-wrap: anywhere;
		margin: 2px 0 0;
		font-weight: 650;
		line-height: 1.3;
	}
	.book-meta {
		margin: 2px 0 0;
		color: var(--muted);
		font-size: 0.85rem;
	}
	.book-switch {
		width: auto;
		min-height: 40px;
		flex: 1 1 100%;
	}
	.chapters {
		padding-top: 22px;
		padding-bottom: 28px;
	}
	.section-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 10px;
	}
	.section-head h2 {
		margin: 0;
		font-size: 1.1rem;
	}
	.chapter {
		padding: 4px 0 12px;
	}
	.chapter-main {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 12px 14px 6px;
		color: var(--text);
		text-decoration: none;
	}
	.chapter-main :global(svg) {
		color: var(--faint);
	}
	.chapter-main:hover .chapter-title {
		color: var(--accent-strong);
	}
	.num {
		display: grid;
		place-items: center;
		width: 38px;
		height: 38px;
		border-radius: 10px;
		background: var(--surface-2);
		border: 1px solid var(--line);
		color: var(--text);
		font-weight: 700;
		font-size: 0.95rem;
		flex-shrink: 0;
	}
	.chapter-title {
		display: block;
		font-weight: 620;
		line-height: 1.35;
		transition: color 0.15s;
	}
	.chapter-meta {
		display: block;
		color: var(--muted);
		font-size: 0.82rem;
	}
	.chapter-actions {
		display: flex;
		gap: 6px;
		padding: 0 14px 0 64px;
		flex-wrap: wrap;
	}
	.mini {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		min-height: 34px;
		padding: 0 12px;
		border-radius: 999px;
		border: 1px solid var(--line);
		background: var(--surface);
		color: var(--muted);
		font-size: 0.84rem;
		font-weight: 600;
		text-decoration: none;
		cursor: pointer;
	}
	.mini:hover {
		background: var(--surface-2);
		color: var(--text);
	}
	.mini.ready {
		color: var(--text);
	}
	.mini :global(svg) {
		color: var(--accent-strong);
	}
	.mini .status-dot {
		width: 7px;
		height: 7px;
	}
</style>
