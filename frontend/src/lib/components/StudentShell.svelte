<script lang="ts">
	import type { Snippet } from 'svelte';
	import { page } from '$app/state';
	import { t } from '#lib/i18n/index.svelte.js';
	import { session } from '#lib/session.svelte.js';
	import Icon from './Icon.svelte';
	import Logo from './Logo.svelte';

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
	const className = $derived(session.me?.class ? `${session.me.class.grade}${session.me.class.section}` : '');
</script>

<div class="shell" class:bare>
	<nav class="rail no-print" aria-label={t('nav.label')}>
		<a class="brand" href="/" aria-label={t('app.name')}>
			<Logo size={32} wordmark />
		</a>
		{#each tabs as tab (tab.href)}
			<a href={tab.href} class="tab" aria-current={active(tab.href) ? 'page' : undefined}>
				<span class="tab-icon"><Icon name={tab.icon} /></span>
				<span>{t(tab.key)}</span>
			</a>
		{/each}
		<div class="rail-foot">
			<p class="offline"><span class="status-dot"></span>{t('app.offline_badge')}</p>
			{#if session.me}
				<div class="me">
					<span class="avatar" aria-hidden="true">{session.me.username.slice(0, 2).toUpperCase()}</span>
					<span class="grow">
						<strong>{session.me.username}</strong>
						{#if className}<small>{t('nav.class', { name: className })}</small>{/if}
					</span>
				</div>
			{/if}
		</div>
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

	/* Phone: a bottom tab bar. */
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
		background: color-mix(in srgb, var(--surface) 88%, transparent);
		backdrop-filter: saturate(1.4) blur(14px);
		-webkit-backdrop-filter: saturate(1.4) blur(14px);
		border-top: 1px solid var(--line);
	}
	.brand,
	.rail-foot {
		display: none;
	}
	.tab {
		flex: 1;
		display: grid;
		justify-items: center;
		gap: 3px;
		padding: 6px 0;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.72rem;
		font-weight: 600;
	}
	.tab-icon {
		display: grid;
		place-items: center;
		width: 56px;
		height: 30px;
		border-radius: 999px;
		transition: background 0.15s;
	}
	.tab[aria-current='page'] {
		color: var(--text);
	}
	.tab[aria-current='page'] .tab-icon {
		background: var(--accent-soft);
		color: var(--accent-strong);
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
		background: color-mix(in srgb, var(--bg) 86%, transparent);
		backdrop-filter: saturate(1.4) blur(14px);
		-webkit-backdrop-filter: saturate(1.4) blur(14px);
		border-bottom: 1px solid var(--line);
	}
	.title {
		flex: 1;
		min-width: 0;
		font-size: 1.05rem;
		font-weight: 650;
		letter-spacing: -0.015em;
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
			grid-template-columns: 240px 1fr;
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
			gap: 2px;
			padding: 20px 12px 14px;
			border-top: 0;
			border-right: 1px solid var(--line);
			background: var(--surface);
		}
		.brand {
			display: flex;
			padding: 2px 10px 22px;
			text-decoration: none;
		}
		.tab {
			flex: 0;
			display: flex;
			align-items: center;
			gap: 10px;
			padding: 8px 10px;
			border-radius: 10px;
			font-size: 0.94rem;
			font-weight: 550;
		}
		.tab-icon {
			width: auto;
			height: auto;
			background: none !important;
		}
		.tab:hover {
			background: var(--surface-2);
			color: var(--text);
		}
		.tab[aria-current='page'] {
			background: var(--surface-2);
			color: var(--text);
			font-weight: 650;
		}
		.tab[aria-current='page'] .tab-icon {
			color: var(--accent-strong);
		}
		.rail-foot {
			display: grid;
			gap: 10px;
			margin-top: auto;
		}
		.offline {
			display: flex;
			align-items: center;
			gap: 10px;
			margin: 0;
			padding: 8px 12px;
			border-radius: 10px;
			background: var(--bg);
			border: 1px solid var(--line);
			font-size: 0.8rem;
			font-weight: 600;
			color: var(--muted);
		}
		.me {
			display: flex;
			align-items: center;
			gap: 10px;
			padding: 10px 8px 2px;
			border-top: 1px solid var(--line);
		}
		.me strong {
			display: block;
			font-size: 0.9rem;
			font-weight: 650;
			overflow: hidden;
			text-overflow: ellipsis;
		}
		.me small {
			display: block;
			color: var(--muted);
			font-size: 0.78rem;
		}
		.avatar {
			display: grid;
			place-items: center;
			width: 34px;
			height: 34px;
			border-radius: 50%;
			background: var(--accent-soft);
			color: var(--accent-strong);
			font-size: 0.78rem;
			font-weight: 700;
			flex-shrink: 0;
		}
	}
</style>
