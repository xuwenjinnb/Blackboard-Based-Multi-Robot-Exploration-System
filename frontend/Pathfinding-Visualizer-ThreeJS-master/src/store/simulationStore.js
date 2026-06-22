import Vue from "vue";
import { adaptSnapshot } from "@/adapters/backendSnapshotAdapter";

export const simulationStore = Vue.observable({
	connected: false,
	loading: false,
	error: null,
	rawSnapshot: null,
	viewState: null,
});

export function applySnapshot(snapshot, previousGridOverride = null) {
	const previousGrid =
		previousGridOverride || (simulationStore.viewState && simulationStore.viewState.grid);
	simulationStore.rawSnapshot = snapshot;
	simulationStore.viewState = adaptSnapshot(snapshot, previousGrid);
}

export function setConnected(value) {
	simulationStore.connected = value;
}

export function setLoading(value) {
	simulationStore.loading = value;
}

export function setError(error) {
	simulationStore.error = error ? String(error.message || error) : null;
}
