<script lang="ts">
	import { t } from '#lib/i18n/index.svelte.js';
	import { renderMarkdown } from '#lib/markdown.js';
	import type { SolutionCard } from '#lib/study.svelte.js';
	import Icon from './Icon.svelte';

	let {
		card,
		language = '',
		oncite
	}: { card: SolutionCard; language?: string; oncite: (event: MouseEvent) => void } = $props();

	// Hint-first (ANSWER_POLICY §3) without another model call: steps open one at a time, and the
	// last line, which holds the answer, opens only with "Show answer" after the student has tried.
	const lastStep = $derived(card.steps.length - 1);
	let opened = $state(1);
	let answerShown = $state(false);
	const visible = $derived(card.steps.slice(0, answerShown ? card.steps.length : Math.min(opened, lastStep)));
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="solution" lang={language || undefined} onclick={oncite}>
	<div class="prose">{@html renderMarkdown(card.idea, true)}</div>

	{#if visible.length}
		<ol class="steps">
			{#each visible as step, index (index)}
				<li>
					<span class="num tabular">{index + 1}</span>
					<div class="step">
						{#if step.why}<div class="prose why">{@html renderMarkdown(step.why, true)}</div>{/if}
						<!-- The calculator's line, exactly as SymPy wrote it: never model text. -->
						<p class="line tabular" lang="en" dir="ltr">{step.line}</p>
					</div>
				</li>
			{/each}
		</ol>
	{/if}

	{#if answerShown}
		<div class="box result">
			<p class="box-title"><Icon name="check" size={17} />{t('solve.answer')}</p>
			<p class="result-value tabular" lang="en" dir="ltr">{card.answers.join(', ')}</p>
			<p class="checked"><Icon name="shield" size={14} />{t('solve.checked')}</p>
		</div>
	{:else}
		<div class="actions">
			{#if opened < lastStep}
				<button class="btn soft" onclick={() => opened++}>
					<Icon name="chevronDown" size={18} />{t('solve.next_step')}
				</button>
			{/if}
			<p class="hint">{t('solve.try_first')}</p>
			<button class="btn soft block" onclick={() => (answerShown = true)}>
				<Icon name="eye" size={18} />{t('solve.show_answer')}
			</button>
		</div>
	{/if}

	{#if card.try_problem}
		<div class="box try">
			<p class="box-title"><Icon name="pencil" size={17} />{t('solve.try_this')}</p>
			<p>{card.try_problem}</p>
		</div>
	{/if}
</div>

<style>
	.solution {
		display: grid;
		gap: 14px;
	}
	.prose {
		font-size: 1.02rem;
		line-height: 1.65;
	}
	.prose :global(p) {
		margin: 0;
	}
	.prose :global(strong) {
		font-weight: 650;
	}
	.prose :global(.cite) {
		display: inline-grid;
		place-items: center;
		min-width: 19px;
		height: 19px;
		margin: 0 1px 0 3px;
		padding: 0 5px;
		border: 1px solid var(--accent-soft);
		border-radius: 6px;
		background: var(--accent-softer);
		color: var(--accent-strong);
		font-size: 0.68rem;
		font-weight: 700;
		line-height: 1;
		vertical-align: 0.25em;
		cursor: pointer;
	}
	.steps {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 12px;
	}
	.steps li {
		display: flex;
		gap: 10px;
		align-items: flex-start;
	}
	.num {
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		border-radius: 50%;
		background: var(--accent-softer);
		border: 1px solid var(--accent-soft);
		color: var(--accent-strong);
		font-weight: 700;
		font-size: 0.85rem;
		flex-shrink: 0;
	}
	.step {
		min-width: 0;
		display: grid;
		gap: 6px;
		flex: 1;
	}
	.why {
		font-size: 0.98rem;
	}
	/* The maths line: large and easy to copy into a notebook. */
	.line {
		margin: 0;
		padding: 8px 12px;
		border-radius: 10px;
		background: var(--surface-2);
		border: 1px solid var(--line);
		font-size: 1.12rem;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.actions {
		display: grid;
		gap: 8px;
		justify-items: start;
	}
	.hint {
		margin: 0;
		font-size: 0.86rem;
		color: var(--muted);
	}
	.box {
		border-radius: 14px;
		padding: 12px 14px;
	}
	.box p {
		margin: 0;
	}
	.box-title {
		display: flex;
		align-items: center;
		gap: 7px;
		font-weight: 650;
		font-size: 0.86rem;
		margin-bottom: 6px !important;
	}
	.result {
		background: var(--accent-softer);
		border: 1.5px solid var(--accent);
	}
	.result .box-title {
		color: var(--accent-strong);
	}
	.result-value {
		font-size: 1.3rem;
		font-weight: 700;
		overflow-wrap: anywhere;
	}
	.checked {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 6px !important;
		font-size: 0.78rem;
		color: var(--ok);
		font-weight: 600;
	}
	.try {
		border: 1.5px dashed var(--line-strong);
	}
	.try .box-title {
		color: var(--accent-strong);
	}
</style>
