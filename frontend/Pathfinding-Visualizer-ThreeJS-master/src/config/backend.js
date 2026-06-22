const isDev = process.env.NODE_ENV === "development";

export const API_BASE_URL = isDev ? "http://127.0.0.1:8000" : "";

export const WS_BASE_URL = isDev
	? "ws://127.0.0.1:8000"
	: `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;
