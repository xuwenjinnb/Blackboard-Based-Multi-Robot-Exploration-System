import { API_BASE_URL } from "@/config/backend";

const TOKEN_KEY = "inspection-auth-token";

export function getToken() {
	return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
	if (token) localStorage.setItem(TOKEN_KEY, token);
	else localStorage.removeItem(TOKEN_KEY);
}

async function request(path, options = {}) {
	const token = getToken();
	const response = await fetch(`${API_BASE_URL}${path}`, {
		headers: {
			"Content-Type": "application/json",
			...(token ? { Authorization: `Bearer ${token}` } : {}),
			...(options.headers || {}),
		},
		...options,
	});

	if (!response.ok) {
		const text = await response.text();
		let message = text;
		try {
			message = JSON.parse(text).detail || text;
		} catch (error) {
			// Keep plain-text server errors unchanged.
		}
		throw new Error(message || `HTTP ${response.status}`);
	}

	if (response.status === 204) return null;
	return response.json();
}

export function login(username, password) {
	return request("/auth/login", {
		method: "POST",
		body: JSON.stringify({ username, password }),
	});
}

export function fetchCurrentUser() {
	return request("/auth/me");
}

export function logout() {
	return request("/auth/logout", { method: "POST" });
}

export function fetchUsers() {
	return request("/admin/users");
}

export function createUser(payload) {
	return request("/admin/users", { method: "POST", body: JSON.stringify(payload) });
}

export function updateUser(username, payload) {
	return request(`/admin/users/${encodeURIComponent(username)}`, {
		method: "PUT",
		body: JSON.stringify(payload),
	});
}

export function deleteUser(username) {
	return request(`/admin/users/${encodeURIComponent(username)}`, { method: "DELETE" });
}

export function fetchReplays() {
	return request("/replays");
}

export function fetchReplay(replayId) {
	return request(`/replays/${encodeURIComponent(replayId)}?maxFrames=90`);
}

export function deleteReplay(replayId) {
	return request(`/replays/${encodeURIComponent(replayId)}`, { method: "DELETE" });
}

export function fetchState() {
	return request("/state");
}

export function fetchRuntime() {
	return request("/runtime");
}

export function startSimulation(payload = {}) {
	return request("/control/start", {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function pauseSimulation() {
	return request("/control/pause", { method: "POST" });
}

export function resumeSimulation() {
	return request("/control/resume", { method: "POST" });
}

export function stopSimulation() {
	return request("/control/stop", { method: "POST" });
}

export function resetSimulation() {
	return request("/control/reset", { method: "POST" });
}

export function setPolicy(policy) {
	return request("/runtime/policy", {
		method: "POST",
		body: JSON.stringify({ policy }),
	});
}

export function setNavigatorAlgorithm(navigatorAlgorithm) {
	return request("/runtime/navigator", {
		method: "POST",
		body: JSON.stringify({ navigatorAlgorithm }),
	});
}

export function setVehicles(payload) {
	return request("/runtime/vehicles", {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function setMap(payload) {
	return request("/runtime/map", {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function setObstacles(payload) {
	return request("/runtime/obstacles", {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function setObstacleCell(payload) {
	return request("/runtime/obstacles/cell", {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export function setObstacleCells(payload) {
	return request("/runtime/obstacles/cells", {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

const api = {
	login: async (username, password) => {
		const result = await login(username, password);
		setToken(result.token);
		return result;
	},
	currentUser: fetchCurrentUser,
	logout: async () => {
		try {
			return await logout();
		} finally {
			setToken("");
		}
	},
	clearToken: () => setToken(""),
	listUsers: fetchUsers,
	createUser,
	updateUser,
	deleteUser,
	listReplays: fetchReplays,
	getReplay: fetchReplay,
	deleteReplay,
};

export default api;
