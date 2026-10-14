<script lang="ts" generics="T extends string">
	import type { Snippet } from 'svelte';
	import { LANGUAGES, getLang, setLang, t, type Lang } from '#lib/i18n/index.svelte.js';
	import { logout, session } from '#lib/session.svelte.js';
	import Icon from './Icon.svelte';

	// Teacher and admin layout: a sidebar on laptops, a scrolling tab strip on phones.
	let {
		role,
		items,
		current,
		onselect,
		title,
		children
	}: {
		role: string;
		items: { id: T; icon: string; label: string; count?: number }[];
		current: T;
		onselect: (id: T) => void;
		title: string;
		children: Snippet;
	} = $props();
</script>

<div class="console">
	<aside class="side no-print">
		<div class="brand"><span class="logo">R</span><div><strong>{t('app.name')}</strong><span>{role}</span></div></div>
		<nav aria-label={role}>
			{#each items as item (item.id)}
				<button class="nav" aria-current={item.id === current ? 'page' : undefined} onclick={() => onselect(item.id)}>
					<Icon name={item.icon} size={20} />
					<span class="grow">{item.label}</span>
					{#if item.count}<span class="count">{item.count}</span>{/if}
				</button>
			{/each}
		</nav>
		<div class="foot">
			<select value={getLang()} onchange={(event) => setLang(event.currentTarget.value as Lang)} aria-label={t('settings.app_language')}>
				{#each LANGUAGES as language (language.code)}<option value={language.code}>{language.label}</option>{/each}
			</select>
			<button class="btn ghost block" onclick={logout}><Icon name="logout" size={18} />{t('logout')}</button>
			<span class="who">{session.me?.username}</span>
		</div>
	</aside>
	<div class="content">
		<header class="top no-print">
			<h1>{title}</h1>
		</header>
		<main>{@render children()}</main>
	</div>
</div>

<style>
	.console {
		min-height: 100dvh;
		display: grid;
		grid-template-columns: 1fr;
	}
	.side {
		position: sticky;
		top: 0;
		z-index: 10;
		background: var(--surface);
		border-bottom: 1px solid var(--line);
		padding: 8px 12px;
		display: grid;
		gap: 6px;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.brand div {
		display: grid;
		line-height: 1.2;
	}
	.brand span:not(.logo) {
		font-size: 0.78rem;
		color: var(--muted);
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
	nav {
		display: flex;
		gap: 4px;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.nav {
		display: flex;
		align-items: center;
		gap: 8px;
		min-height: 40px;
		padding: 0 12px;
		border: 0;
		border-radius: 10px;
		background: transparent;
		color: var(--muted);
		font-weight: 650;
		cursor: pointer;
		white-space: nowrap;
		text-align: left;
	}
	.nav:hover {
		background: var(--surface-2);
	}
	.nav[aria-current='page'] {
		background: var(--accent-soft);
		color: var(--accent-strong);
	}
	.count {
		min-width: 22px;
		padding: 0 6px;
		border-radius: 999px;
		background: var(--warm);
		color: #fff;
		font-size: 0.75rem;
		text-align: center;
	}
	.foot {
		display: none;
	}
	.content {
		min-width: 0;
	}
	.top {
		padding: 18px 16px 4px;
	}
	.top h1 {
		margin: 0;
		font-size: 1.4rem;
	}
	main {
		padding: 12px 16px 40px;
	}
	@media (min-width: 900px) {
		.console {
			grid-template-columns: 250px 1fr;
		}
		.side {
			height: 100dvh;
			border-bottom: 0;
			border-right: 1px solid var(--line);
			padding: 18px 12px;
			grid-template-rows: auto 1fr auto;
			gap: 18px;
		}
		.brand {
			padding: 0 8px;
		}
		nav {
			flex-direction: column;
			overflow: visible;
		}
		.nav {
			min-height: 44px;
		}
		.foot {
			display: grid;
			gap: 8px;
		}
		.foot select {
			min-height: 40px;
		}
		.who {
			text-align: center;
			font-size: 0.8rem;
			color: var(--muted);
		}
		.top {
			padding: 26px 32px 6px;
		}
		main {
			padding: 12px 32px 48px;
			max-width: 1180px;
		}
	}
</style>
