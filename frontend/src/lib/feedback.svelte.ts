// App-styled replacements for window.alert() and window.confirm(). Toaster.svelte and
// ConfirmDialog.svelte are mounted once in the root layout and render this state.

export type ToastKind = 'ok' | 'error' | 'info';
type Toast = { id: number; message: string; kind: ToastKind };
type PendingConfirm = {
	message: string;
	danger: boolean;
	confirmLabel: string;
	resolve: (answer: boolean) => void;
};

export const feedback = $state<{ toasts: Toast[]; confirm: PendingConfirm | null }>({
	toasts: [],
	confirm: null
});

let nextId = 0;

export function toast(message: string, kind: ToastKind = 'info', durationMs = 4500): void {
	const id = ++nextId;
	feedback.toasts.push({ id, message, kind });
	setTimeout(() => dismissToast(id), durationMs);
}

export function dismissToast(id: number): void {
	feedback.toasts = feedback.toasts.filter((item) => item.id !== id);
}

/** Resolves true when the user confirms, false when they cancel or close the dialog. */
export function confirmAction(
	message: string,
	{ danger = false, confirmLabel = '' }: { danger?: boolean; confirmLabel?: string } = {}
): Promise<boolean> {
	feedback.confirm?.resolve(false); // only one question at a time
	return new Promise((resolve) => {
		feedback.confirm = { message, danger, confirmLabel, resolve };
	});
}

export function settleConfirm(answer: boolean): void {
	const pending = feedback.confirm;
	feedback.confirm = null;
	pending?.resolve(answer);
}
