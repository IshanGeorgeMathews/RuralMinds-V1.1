<script lang="ts">
	import { api, ApiError, uploadFile } from '#lib/api.js';
	import { t } from '#lib/i18n/index.svelte.js';

	type ClassRow = { id: number; label: string; medium: string };
	type ChapterRow = { no: number; title: string; start: number };

	let {
		classes,
		limits,
		subjects,
		boards,
		resumeJob = null,
		ondone
	}: {
		classes: ClassRow[];
		limits: { max_upload_mb: number; max_pages: number };
		subjects: string[];
		boards: string[];
		resumeJob?: { id: number; page_count: number; filename: string } | null;
		ondone: () => void;
	} = $props();

	let jobId = $state<number | null>(resumeJob?.id ?? null);
	let pageCount = $state(resumeJob?.page_count ?? 0);
	let progress = $state<number | null>(null);
	let errors = $state<string[]>([]);
	let fromBookmarks = $state(false);
	let saving = $state(false);

	let title = $state(resumeJob ? titleFrom(resumeJob.filename) : '');
	let grade = $state(8);
	let subject = $state('social_science');
	let medium = $state<'en' | 'ml'>('en');
	let board = $state('SCERT-KL');
	let pageOffset = $state(0);
	let lastPage = $state<number | null>(resumeJob?.page_count ?? null);
	let chapters = $state<ChapterRow[]>([{ no: 1, title: '', start: 1 }]);
	let classIds = $state<number[]>([]);

	function titleFrom(filename: string): string {
		return filename.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' ').trim();
	}

	async function pick(event: Event): Promise<void> {
		const file = (event.currentTarget as HTMLInputElement).files?.[0];
		errors = [];
		if (!file) return;
		// Checked here for a quick answer; the server checks again while receiving.
		if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
			errors = ['upload.not_pdf'];
			return;
		}
		if (file.size > limits.max_upload_mb * 1024 * 1024) {
			errors = ['upload.too_big'];
			return;
		}
		try {
			const { job_id } = await api.post<{ job_id: number }>('/api/teacher/uploads', {
				filename: file.name
			});
			jobId = job_id;
			progress = 0;
			const info = await uploadFile(`/api/teacher/uploads/${job_id}/file`, file, (fraction) => {
				progress = Math.round(fraction * 100);
			});
			pageCount = info.page_count;
			lastPage = info.page_count;
			title = titleFrom(file.name);
			if (info.bookmarks.length) {
				chapters = info.bookmarks.map((mark: { title: string; page: number }, index: number) => ({
					no: index + 1,
					title: mark.title,
					start: mark.page
				}));
				fromBookmarks = true;
			}
		} catch (error) {
			errors = [error instanceof ApiError ? error.key : 'error.generic'];
			if (jobId !== null) await api.del(`/api/teacher/uploads/${jobId}`).catch(() => {});
			jobId = null;
		} finally {
			progress = null;
		}
	}

	function addChapter(): void {
		const last = chapters[chapters.length - 1];
		chapters.push({ no: (last?.no ?? 0) + 1, title: '', start: Math.min(pageCount, (last?.start ?? 0) + 1) });
	}

	async function save(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		errors = [];
		saving = true;
		try {
			await api.post(`/api/teacher/uploads/${jobId}/details`, {
				title,
				grade,
				subject,
				medium,
				board,
				page_offset: pageOffset,
				last_page: lastPage,
				chapters,
				class_ids: classIds
			});
			alert(t('upload.queued'));
			ondone();
		} catch (error) {
			errors = error instanceof ApiError ? error.keys : ['error.generic'];
		} finally {
			saving = false;
		}
	}
</script>

<section class="card stack">
	{#if jobId === null || progress !== null}
		<h2>{t('upload.step_file')}</h2>
		<p class="muted">{t('upload.limit', { mb: limits.max_upload_mb, pages: limits.max_pages })}</p>
		{#if progress !== null}
			<div class="bar" role="progressbar" aria-valuenow={progress} aria-valuemin="0" aria-valuemax="100">
				<span style={`width:${progress}%`}></span>
			</div>
			<p>{t('upload.sending', { pct: progress })}</p>
		{:else}
			<label class="btn primary pick">
				📄 {t('upload.choose')}
				<input type="file" accept="application/pdf,.pdf" onchange={pick} class="sr-only" />
			</label>
		{/if}
	{:else}
		<h2>{t('upload.step_details')}</h2>
		<p class="muted">{t('teacher.pages', { n: pageCount })}</p>
		<form class="stack" onsubmit={save}>
			<label class="field"><span>{t('upload.title')}</span><input bind:value={title} required maxlength="120" /></label>
			<div class="grid">
				<label class="field"><span>{t('upload.grade')}</span>
					<input type="number" bind:value={grade} min="1" max="12" required /></label>
				<label class="field"><span>{t('upload.subject')}</span>
					<select bind:value={subject}>
						{#each subjects as option (option)}<option value={option}>{t(`subject.${option}`)}</option>{/each}
					</select></label>
				<label class="field"><span>{t('upload.medium')}</span>
					<select bind:value={medium}>
						<option value="en">{t('medium.en')}</option>
						<option value="ml">{t('medium.ml')}</option>
					</select></label>
				<label class="field"><span>{t('upload.board')}</span>
					<select bind:value={board}>
						{#each boards as option (option)}<option value={option}>{option}</option>{/each}
					</select></label>
			</div>
			<div class="grid">
				<label class="field"><span>{t('upload.page_offset')}</span>
					<input type="number" bind:value={pageOffset} min="-500" max="500" />
					<small class="muted">{t('upload.page_offset_help')}</small></label>
				<label class="field"><span>{t('upload.last_page')}</span>
					<input type="number" bind:value={lastPage} min="1" max={pageCount} /></label>
			</div>

			<fieldset class="stack">
				<legend>{t('upload.chapters')}</legend>
				<p class="muted small">
					{t('upload.chapters_help', { found: fromBookmarks ? t('upload.bookmarks_found') : '' })}
				</p>
				{#each chapters as chapter, index (index)}
					<div class="chapter">
						<input type="number" bind:value={chapter.no} min="1" max="99" aria-label={t('upload.chapter_no')} />
						<input bind:value={chapter.title} required maxlength="120" placeholder={t('upload.chapter_title')} aria-label={t('upload.chapter_title')} />
						<input type="number" bind:value={chapter.start} min="1" max={pageCount} aria-label={t('upload.chapter_start')} title={t('upload.chapter_start')} />
						<button type="button" class="btn small ghost" onclick={() => chapters.splice(index, 1)} disabled={chapters.length === 1} aria-label={t('upload.remove')}>✕</button>
					</div>
				{/each}
				<div class="row muted small"><span class="grow">{t('upload.chapter_title')}</span><span>{t('upload.chapter_start')}</span></div>
				<button type="button" class="btn small" onclick={addChapter}>＋ {t('upload.add_chapter')}</button>
			</fieldset>

			<fieldset>
				<legend>{t('upload.classes')}</legend>
				<div class="row">
					{#each classes as klass (klass.id)}
						<label class="chip"><input type="checkbox" bind:group={classIds} value={klass.id} /> {klass.label} · {t(`medium.${klass.medium}`)}</label>
					{/each}
				</div>
			</fieldset>

			{#if errors.length}
				<div class="error" role="alert">{#each errors as key (key)}<p>{t(key)}</p>{/each}</div>
			{/if}
			<button class="btn primary" disabled={saving}>{t('upload.submit')}</button>
		</form>
	{/if}
	{#if errors.length && jobId === null}
		<div class="error" role="alert">{#each errors as key (key)}<p>{t(key)}</p>{/each}</div>
	{/if}
</section>

<style>
	.pick {
		justify-self: start;
		cursor: pointer;
	}
	.bar {
		height: 12px;
		border-radius: 999px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.bar span {
		display: block;
		height: 100%;
		background: var(--accent);
		transition: width 0.2s;
	}
	.grid {
		display: grid;
		gap: 0 12px;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
	}
	fieldset {
		border: 1px solid var(--line);
		border-radius: 12px;
		padding: 12px;
		margin: 0;
	}
	legend {
		font-weight: 700;
		padding: 0 6px;
	}
	.chapter {
		display: grid;
		grid-template-columns: 64px 1fr 84px 40px;
		gap: 6px;
		align-items: center;
	}
	.small {
		font-size: 0.85rem;
		margin: 0;
	}
	.error p {
		margin: 2px 0;
	}
</style>
