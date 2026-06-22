import { WS_BASE_URL } from "@/config/backend";
import { getToken } from "@/services/api";

export function createSimulationSocket({ onSnapshot, onOpen, onClose, onError }) {
	let socket = null;
	let reconnectTimer = null;
	let stopped = false;

	function connect() {
		socket = new WebSocket(`${WS_BASE_URL}/ws?token=${encodeURIComponent(getToken())}`);

		socket.onopen = () => {
			if (onOpen) onOpen();
		};

		socket.onmessage = (event) => {
			try {
				const message = JSON.parse(event.data);
				if (message.type === "STATE_SNAPSHOT" && onSnapshot) {
					onSnapshot(message.payload);
				}
			} catch (error) {
				if (onError) onError(error);
			}
		};

		socket.onerror = (error) => {
			if (onError) onError(error);
		};

		socket.onclose = () => {
			if (onClose) onClose();
			if (!stopped) {
				reconnectTimer = setTimeout(connect, 1200);
			}
		};
	}

	connect();

	return {
		close() {
			stopped = true;
			if (reconnectTimer) clearTimeout(reconnectTimer);
			if (socket) socket.close();
		},
		send(message) {
			if (socket && socket.readyState === WebSocket.OPEN) {
				socket.send(JSON.stringify(message));
			}
		},
	};
}
