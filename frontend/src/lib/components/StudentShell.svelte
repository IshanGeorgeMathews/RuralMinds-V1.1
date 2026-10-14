<script lang="ts">
	import type { Snippet } from 'svelte';
	import { page } from '$app/state';
	import { t } from '#lib/i18n/index.svelte.js';
	import { session } from '#lib/session.svelte.js';
	import Icon from './Icon.svelte';

	let {
		title = '',
		back = '',
		actions,
		children,
		bare = false
	}: { title?: string; back?: string; actions?: Snippet; children: Snippet; bare?: boolean } =
		$props();

	const tabs = [
		{ href: '/', icon: 'home', key: 'nav.learn' },
		{ href: '/ask', icon: 'chat', key: 'nav.ask' },
		{ href: '/settings', icon: 'settings', key: 'nav.settings' }
	];
	const active = (href: string) =>
		href === '/' ? page.url.pathname === '/' || page.url.pathname.startsWith('/learn') : page.url.pathname.startsWith(href);
</script>

<div class="shell" class:bare>
	<nav class="rail no-print" aria-label={t('nav.label')}>
		<a class="brand" href="/" aria-label={t('app.name')}>
			<span class="logo">R</span><span class="brand-name">{t('app.name')}</span>
		</a>
		{#each tabs as tab (tab.href)}
			<a href={tab.href} class="tab" aria-current={active(tab.href) ? 'page' : undefined}>
				<Icon name={tab.icon} />
				<span>{t(tab.key)}</span>
			</a>
		{/each}
		{#if session.me?.class}
			<span class="class-badge">{t('nav.class', { name: `${session.me.class.grade}${session.me.class.section}` })}</span>
		{/if}
	</nav>

	<div class="main">
		{#if title || back || actions}
			<header class="appbar no-print">
				{#if back}
					<a class="btn ghost icon" href={back} aria-label={t('common.back')}><Icon name="chevronLeft" /></a>
				{/if}
				<h1 class="title">{title}</h1>
				<div class="actions">{@render actions?.()}</div>
			</header>
		{/if}
		{@render children()}
	</div>
</div>

<style>
	.shell {
		min-height: 100dvh;
		display: grid;
		grid-template-columns: 1fr;
	}
	.main {
		min-width: 0;
		padding-bottom: calc(var(--nav-height) + env(safe-area-inset-bottom));
	}
	.bare .main {
		padding-bottom: 0;
	}
	.rail {
		position: fixed;
		z-index: 20;
		left: 0;
		right: 0;
		bottom: 0;
		height: calc(var(--nav-height) + env(safe-area-inset-bottom));
		padding-bottom: env(safe-area-inset-bottom);
		display: flex;
		justify-content: space-around;
		align-items: center;
		background: color-mix(in srgb, var(--surface) 94%, transparent);
		backdrop-filter: blur(12px);
		border-top: 1px solid var(--line);
	}
	.brand,
	.class-badge {
		display: none;
	}
	.tab {
		flex: 1;
		display: grid;
		justify-items: center;
		gap: 2px;
		padding: 6px 0;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.72rem;
		font-weight: 650;
	}
	.tab[aria-current='page'] {
		color: var(--accent-strong);
	}
	.tab[aria-current='page'] :global(svg) {
		background: var(--accent-soft);
		border-radius: 999px;
		padding: 3px 14px;
		width: 52px;
		box-sizing: content-box;
		margin: -3px 0;
	}
	.appbar {
		position: sticky;
		top: 0;
		z-index: 10;
		display: flex;
		align-items: center;
		gap: 6px;
		min-height: 58px;
		padding: 6px 12px;
		background: color-mix(in srgb, var(--bg) 90%, transparent);
		backdrop-filter: blur(12px);
		border-bottom: 1px solid var(--line);
	}
	.title {
		flex: 1;
		min-width: 0;
		font-size: 1.1rem;
		margin: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		padding-left: 4px;
	}
	.actions {
		display: flex;
		gap: 4px;
		align-items: center;
	}

	/* Tablet / laptop: a left rail instead of a bottom bar. */
	@media (min-width: 900px) {
		.shell {
			grid-template-columns: 220px 1fr;
		}
		.main {
			padding-bottom: 0;
		}
		.rail {
			position: sticky;
			top: 0;
			height: 100dvh;
			flex-direction: column;
			justify-content: flex-start;
			align-items: stretch;
			gap: 4px;
			padding: 18px 12px;
			border-top: 0;
			border-right: 1px solid var(--line);
		}
		.brand {
			display: flex;
			align-items: center;
			gap: 10px;
			padding: 4px 8px 18px;
			color: var(--text);
			text-decoration: none;
			font-weight: 800;
			font-size: 1.1rem;
		}
		.class-badge {
			display: block;
			margin-top: auto;
			padding: 8px 12px;
			color: var(--muted);
			font-size: 0.85rem;
		}
		.tab {
			flex: 0;
			display: flex;
			align-items: center;
			gap: 12px;
			padding: 10px 12px;
			border-radius: 12px;
			font-size: 0.95rem;
		}
		.tab:hover {
			background: var(--surface-2);
		}
		.tab[aria-current='page'] {
			background: var(--accent-soft);
		}
		.tab[aria-current='page'] :global(svg) {
			background: none;
			padding: 0;
			width: auto;
			margin: 0;
		}
	}
	.logo {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 10px;
		background: linear-gradient(135deg, var(--accent), var(--accent-strong));
		color: #fff;
		font-weight: 800;
	}
</style>
