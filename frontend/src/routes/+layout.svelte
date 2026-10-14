<script lang="ts">
	import '../app.css';
	import '#lib/prefs.svelte.js'; // applies text size and theme before the first paint
	import favicon from '#lib/assets/favicon.svg';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{@render children()}
