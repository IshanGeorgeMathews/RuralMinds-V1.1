<script lang="ts">
	import type { Snippet } from 'svelte';
	import { onMount } from 'svelte';
	import { ApiError } from '#lib/api.js';
	import { t } from '#lib/i18n/index.svelte.js';
	import { requireRole } from '#lib/session.svelte.js';
	import { loadCatalog, study } from '#lib/study.svelte.js';
	import Icon from './Icon.svelte';

	// Signs the student in (or redirects) and loads their books once for all student screens.
	let { children }: { children: Snippet } = $props();
	let errorKey = $state('');

	async function load(): Promise<void> {
		errorKey = '';
		try {
			if (!(await requireRole('student'))) return;
			if (!study.loaded || study.endpoint !== '/api/ask') await loadCatalog();
		} catch (error) {
			errorKey = error instanceof ApiError ? error.key : 'error.generic';
		}
	}

	onMount(load);
</script>

{#if errorKey}
	<div class="wrap">
		<div class="empty">
			<div class="art"><Icon name="wifiOff" size={30} /></div>
			<p>{t(errorKey)}</p>
			<button class="btn primary" onclick={load}>{t('retry')}</button>
		</div>
	</div>
{:else if !study.loaded}
	<div class="wrap loading" aria-busy="true">
		<div class="skeleton" style="height:140px"></div>
		<div class="skeleton" style="height:84px"></div>
		<div class="skeleton" style="height:84px"></div>
	</div>
{:else if study.books.length === 0}
	<div class="wrap">
		<div class="empty">
			<div class="art"><Icon name="book" size={30} /></div>
			<p>{t('student.no_books')}</p>
		</div>
	</div>
{:else}
	{@render children()}
{/if}

<style>
	.loading {
		display: grid;
		gap: 12px;
		padding-top: 16px;
	}
</style>
