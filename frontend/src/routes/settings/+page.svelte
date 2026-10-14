<script lang="ts">
	import Icon from '#lib/components/Icon.svelte';
	import StudentGate from '#lib/components/StudentGate.svelte';
	import StudentShell from '#lib/components/StudentShell.svelte';
	import { LANGUAGES, getLang, setLang, t, type Lang } from '#lib/i18n/index.svelte.js';
	import { prefs, savePrefs } from '#lib/prefs.svelte.js';
	import { logout, session } from '#lib/session.svelte.js';
</script>

<StudentShell title={t('nav.settings')}>
	<StudentGate>
		<main class="wrap stack page">
			<section class="card group">
				<div class="row-head"><Icon name="globe" /><div><h2>{t('settings.app_language')}</h2><p class="muted small">{t('settings.app_language_help')}</p></div></div>
				<select value={getLang()} onchange={(event) => setLang(event.currentTarget.value as Lang)} aria-label={t('settings.app_language')}>
					{#each LANGUAGES as language (language.code)}<option value={language.code}>{language.label}</option>{/each}
				</select>
			</section>

			<section class="card group">
				<div class="row-head"><Icon name="chat" /><div><h2>{t('settings.answer_language')}</h2><p class="muted small">{t('settings.answer_language_help')}</p></div></div>
				<div class="segmented" role="radiogroup" aria-label={t('settings.answer_language')}>
					{#each ['auto', 'en', 'ml'] as option (option)}
						<button role="radio" aria-checked={prefs.answerLanguage === option} onclick={() => ((prefs.answerLanguage = option as typeof prefs.answerLanguage), savePrefs())}>
							{t(`settings.answer.${option}`)}
						</button>
					{/each}
				</div>
			</section>

			<section class="card group">
				<div class="row-head"><Icon name="text" /><div><h2>{t('settings.text_size')}</h2></div></div>
				<div class="segmented" role="radiogroup" aria-label={t('settings.text_size')}>
					{#each [['md', 'A'], ['lg', 'A+'], ['xl', 'A++']] as [size, label] (size)}
						<button role="radio" aria-checked={prefs.textSize === size} class={`size-${size}`} onclick={() => ((prefs.textSize = size as typeof prefs.textSize), savePrefs())}>{label}</button>
					{/each}
				</div>
			</section>

			<section class="card group">
				<div class="row-head"><Icon name="moon" /><div><h2>{t('settings.theme')}</h2></div></div>
				<div class="segmented" role="radiogroup" aria-label={t('settings.theme')}>
					{#each ['system', 'light', 'dark'] as theme (theme)}
						<button role="radio" aria-checked={prefs.theme === theme} onclick={() => ((prefs.theme = theme as typeof prefs.theme), savePrefs())}>{t(`settings.theme.${theme}`)}</button>
					{/each}
				</div>
			</section>

			<section class="card group">
				<div class="row-head"><Icon name="shield" /><div><h2>{t('settings.privacy')}</h2><p class="muted small">{t('settings.privacy_body')}</p></div></div>
			</section>

			<button class="btn danger block" onclick={logout}><Icon name="logout" size={18} />{t('logout')} · {session.me?.username}</button>
		</main>
	</StudentGate>
</StudentShell>

<style>
	.page {
		padding-top: 14px;
		padding-bottom: 24px;
	}
	.group {
		display: grid;
		gap: 12px;
	}
	.row-head {
		display: flex;
		gap: 12px;
		align-items: flex-start;
	}
	.row-head :global(svg) {
		color: var(--accent-strong);
		margin-top: 2px;
	}
	.row-head h2 {
		font-size: 1rem;
		margin: 0;
	}
	.row-head p {
		margin: 2px 0 0;
	}
	.small {
		font-size: 0.85rem;
	}
	.segmented {
		display: grid;
		grid-auto-flow: column;
		grid-auto-columns: 1fr;
		gap: 4px;
		padding: 4px;
		border-radius: 14px;
		background: var(--surface-2);
	}
	.segmented button {
		min-height: 42px;
		border: 0;
		border-radius: 11px;
		background: transparent;
		cursor: pointer;
		font-weight: 650;
		color: var(--muted);
	}
	.segmented button[aria-checked='true'] {
		background: var(--surface);
		color: var(--accent-strong);
		box-shadow: var(--shadow);
	}
	.size-lg {
		font-size: 1.1rem;
	}
	.size-xl {
		font-size: 1.25rem;
	}
</style>
