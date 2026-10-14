<script lang="ts">
	import ChatView from '#lib/components/ChatView.svelte';
	import StudentGate from '#lib/components/StudentGate.svelte';
	import StudentShell from '#lib/components/StudentShell.svelte';
	import { t } from '#lib/i18n/index.svelte.js';
</script>

<StudentShell title={t('nav.ask')}>
	<StudentGate>
		<div class="wrap"><ChatView /></div>
	</StudentGate>
</StudentShell>
