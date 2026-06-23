<template>
	<div class="pathfinding-visualizer" @click="clearFocus">
		<VisualizerCanvas
			ref="visualizer"
			:nodeDimensions="nodeDimensions"
			:rows="displayRows"
			:cols="displayCols"
			:grid="displayGrid"
			:start="start"
			:finish="finish"
			:visualizerState="visualizerState"
			:colors="colors"
			:controlType="controlType"
			:worldSetup="worldSetup"
			:selectedAlgorithm="selectedAlgorithm"
			:streaming="streaming"
			:thresholdValue="thresholdValue"
			:backendMode="true"
			:vehicles="displayVehicles"
			:vehicleModel="backendControls.vehicleModel"
			:frontiers="displayFrontiers"
			:pathsByVehicle="displayPathsByVehicle"
			:showGrid="layers.grid"
			:showFrontiers="layers.frontiers"
			:showPaths="layers.paths"
			:obstacleEditMode="obstacleEditMode"
			:backendChangedCells="displayChangedCells"
			@clickEvent="handleBackendGridClick"
			@paintEvent="handleBackendGridPaint"
			@paintEnd="flushObstaclePaint"
			@groundInitialized="onGroundInitialized"
			@switchControlType="controlType = controlType == 'Orbit' ? 'PointerLock' : 'Orbit'"
		/>

		<transition-group name="slide" mode="out-in" tag="div" class="header py-1">
			<div class="backend-status" key="backend-status">
				<span :class="['dot', simulationStore.connected ? 'online' : 'offline']"></span>
				<span>{{ simulationStore.connected ? "实时连接正常" : "实时连接断开" }}</span>
				<strong>{{ backendStatusLabel }}</strong>
			</div>

			<Button
				class="accent"
				@click.stop="handleBackendStart"
				:disabled="backendBusy || backendStatus === 'RUNNING'"
				key="backend-start"
			>
				<span class="lg">启动</span>
				<span class="sm">启动</span>
			</Button>
			<Button
				class="warning"
				@click.stop="handleBackendPause"
				:disabled="backendBusy || backendStatus !== 'RUNNING'"
				key="backend-pause"
			>
				<span class="lg">暂停</span>
				<span class="sm">暂停</span>
			</Button>
			<Button
				class="accent"
				@click.stop="handleBackendResume"
				:disabled="backendBusy || backendStatus !== 'PAUSED'"
				key="backend-resume"
			>
				<span class="lg">恢复</span>
				<span class="sm">恢复</span>
			</Button>
			<Button
				class="danger"
				@click.stop="handleBackendStop"
				:disabled="backendBusy || backendStatus === 'STOPPED'"
				key="backend-stop"
			>
				<span class="lg">停止</span>
				<span class="sm">停止</span>
			</Button>
			<Button
				class="danger"
				@click.stop="handleBackendReset"
				:disabled="backendBusy"
				key="backend-reset"
			>
				<span class="lg">重置</span>
				<span class="sm">重置</span>
			</Button>

			<select
				id="policy"
				v-model="backendControls.policy"
				:disabled="backendBusy || backendStatus === 'RUNNING'"
				key="policy-select"
				@change="handlePolicyChange"
			>
				<option :value="policy.id" v-for="policy in policyOptions" :key="policy.id">
					{{ policy.name || policy.id }}
				</option>
			</select>
			<select
				id="navigator"
				v-model="backendControls.navigatorAlgorithm"
				:disabled="backendBusy || backendStatus === 'RUNNING'"
				key="navigator-select"
				@change="handleNavigatorChange"
			>
				<option :value="item.id" v-for="item in navigatorOptions" :key="item.id">
					{{ item.name || item.id }}
				</option>
			</select>
			<div class="vehicle-controls" key="vehicle-controls">
				<input
					class="vehicle-count"
					type="number"
					min="1"
					max="12"
					v-model.number="backendControls.vehicleCount"
					:disabled="backendBusy || backendStatus === 'RUNNING'"
					@input="deploymentDirty = true"
					title="车辆数量"
				>
				<Button
					class="info"
					@click.stop="handleVehiclesApply"
					:disabled="backendBusy || backendStatus === 'RUNNING'"
				>
					<span class="lg">车辆 {{ backendControls.vehicleCount }}</span>
					<span class="sm">车辆</span>
				</Button>
				<label class="vehicle-skin-picker" title="车辆皮肤">
					<span>皮肤</span>
					<select
						id="vehicle-skin"
						class="vehicle-skin"
						v-model="backendControls.vehicleModel"
					>
						<option :value="skin.id" v-for="skin in vehicleSkinOptions" :key="skin.id">
							{{ skin.name }}
						</option>
					</select>
				</label>
			</div>
			<input
				class="map-size"
				type="number"
				min="3"
				max="128"
				v-model.number="backendControls.mapWidth"
				:disabled="backendBusy || backendStatus !== 'STOPPED'"
				@input="mapConfigDirty = true"
				key="map-width"
				title="地图宽度"
			>
			<input
				class="map-size"
				type="number"
				min="3"
				max="128"
				v-model.number="backendControls.mapHeight"
				:disabled="backendBusy || backendStatus !== 'STOPPED'"
				@input="mapConfigDirty = true"
				key="map-height"
				title="地图高度"
			>
			<input
				class="map-size"
				type="number"
				min="2"
				max="64"
				v-model.number="backendControls.chunkSize"
				:disabled="backendBusy || backendStatus !== 'STOPPED'"
				@input="mapConfigDirty = true"
				key="chunk-size"
				title="分块大小"
			>
			<Button
				class="info"
				@click.stop="handleMapApply"
				:disabled="backendBusy || backendStatus !== 'STOPPED'"
				key="map-apply"
			>
				<span class="lg">地图 {{ backendControls.mapWidth }}×{{ backendControls.mapHeight }}</span>
				<span class="sm">地图</span>
			</Button>
			<Button
				class="info"
				@click.stop="handleManualObstacles"
				:disabled="backendBusy || backendStatus !== 'STOPPED'"
				key="manual-obstacles"
			>
				<span class="lg">{{ obstacleEditMode ? "结束设置" : "手动障碍" }}</span>
				<span class="sm">{{ obstacleEditMode ? "结束" : "手动" }}</span>
			</Button>
			<input
				class="obstacle-count"
				type="number"
				min="0"
				max="600"
				v-model.number="backendControls.obstacleCount"
				:disabled="backendBusy || backendStatus !== 'STOPPED'"
				key="obstacle-count"
			>
			<Button
				class="warning"
				@click.stop="handleRandomObstacles"
				:disabled="backendBusy || backendStatus !== 'STOPPED'"
				key="random-obstacles"
			>
				<span class="lg">随机障碍</span>
				<span class="sm">随机</span>
			</Button>
			<div class="obstacle-status" key="obstacle-status">
				{{ obstacleEditMode ? "拖动地图增删障碍" : `障碍 ${obstacleCount}` }}
			</div>

			<div class="layer-controls" key="layer-controls" aria-label="显示图层">
				<label><input type="checkbox" v-model="layers.grid">网格线</label>
				<label><input type="checkbox" v-model="layers.frontiers">前沿点</label>
				<label><input type="checkbox" v-model="layers.paths">规划路径</label>
			</div>
		</transition-group>

		<div class="backend-error" v-if="simulationStore.error">
			{{ simulationStore.error }}
		</div>

		<Button
			class="hover btn-controls warning"
			key="switch-controls"
			@click.stop="switchControl"
		>
			<img src="@/assets/icons/street-view.svg" alt="" v-if="controlType == 'Orbit'" />
			<img src="@/assets/icons/perspective.svg" alt="" v-else />
			<span class="lg">{{ controlType == "Orbit" ? "第一人称" : "环绕视角" }}</span>
		</Button>
		<Button
			class="hover btn-camera warning"
			key="reset-camera"
			v-if="controlType == 'Orbit'"
			@click.stop="$refs.visualizer.resetCamera()"
		>
			<img src="@/assets/icons/reset-camera.svg" alt="" />
			<span class="lg">重置相机</span>
		</Button>
		<Info
			ref="info"
			:colors="colors"
		></Info>
	</div>
</template>

<script>
import VisualizerCanvas from "./VisualizerCanvas.vue";
import Info from "@/components/UI/Info.vue";
import {
	fetchState,
	pauseSimulation,
	resetSimulation,
	resumeSimulation,
	setMap,
	setObstacleCell,
	setObstacleCells,
	setObstacles,
	setNavigatorAlgorithm,
	setPolicy,
	setVehicles,
	startSimulation,
	stopSimulation,
} from "@/services/api";
import { createSimulationSocket } from "@/services/ws";
import {
	applySnapshot,
	setConnected,
	setError,
	setLoading,
	simulationStore,
} from "@/store/simulationStore";

const DEFAULT_POLICIES = [
	{ id: "nearest", name: "最近可达前沿" },
	{ id: "greedy", name: "贪心信息增益" },
	{ id: "low_mdp", name: "低层 MDP" },
];

const DEFAULT_NAVIGATORS = [
	{ id: "baseline", name: "基础规划" },
	{ id: "cbs", name: "CBS 冲突搜索" },
];

const VEHICLE_SKINS = [
	{ id: "sedan", name: "轿车" },
	{ id: "sedan-sports", name: "运动轿车" },
	{ id: "hatchback-sports", name: "掀背跑车" },
	{ id: "race", name: "赛车" },
	{ id: "race-future", name: "未来赛车" },
	{ id: "taxi", name: "出租车" },
	{ id: "police", name: "警车" },
	{ id: "ambulance", name: "救护车" },
	{ id: "delivery", name: "配送车" },
	{ id: "delivery-flat", name: "平板配送车" },
	{ id: "van", name: "厢式车" },
	{ id: "suv", name: "SUV" },
	{ id: "suv-luxury", name: "豪华 SUV" },
	{ id: "truck", name: "卡车" },
	{ id: "truck-flat", name: "平板卡车" },
	{ id: "firetruck", name: "消防车" },
	{ id: "garbage-truck", name: "垃圾车" },
	{ id: "tractor", name: "拖拉机" },
	{ id: "tractor-shovel", name: "铲斗拖拉机" },
	{ id: "tractor-police", name: "巡逻拖拉机" },
	{ id: "kart-oodi", name: "卡丁车 Oodi" },
	{ id: "kart-ooli", name: "卡丁车 Ooli" },
	{ id: "kart-oopi", name: "卡丁车 Oopi" },
	{ id: "kart-oobi", name: "卡丁车 Oobi" },
	{ id: "kart-oozi", name: "卡丁车 Oozi" },
];

const POLICY_NAMES = Object.fromEntries(DEFAULT_POLICIES.map((item) => [item.id, item.name]));
const NAVIGATOR_NAMES = Object.fromEntries(DEFAULT_NAVIGATORS.map((item) => [item.id, item.name]));
const STATUS_NAMES = {
	RUNNING: "运行中",
	PAUSED: "已暂停",
	STOPPED: "已停止",
};

export default {
	components: {
		VisualizerCanvas,
		Info,
	},
	data: () => ({
		backendSocket: null,
		backendInitialized: false,
		backendBusy: false,
		deploymentDirty: false,
		mapConfigDirty: false,
		obstacleEditMode: false,
		obstaclePaint: {
			blocked: null,
			cells: [],
			seen: {},
		},
		backendControls: {
			policy: "nearest",
			navigatorAlgorithm: "baseline",
			vehicleCount: 8,
			vehicleModel: "sedan",
			obstacleCount: 120,
			mapWidth: 50,
			mapHeight: 50,
			chunkSize: 10,
		},
		visualizerState: "clear",
		selectedAlgorithm: null,
		nodeDimensions: {
			height: 10,
			width: 10,
		},
		rows: 50,
		cols: 50,
		grid: [],
		ground: null,
		controlType: "Orbit",
		start: {
			row: 3,
			col: 5,
		},
		finish: {
			row: 16,
			col: 22,
		},
		worldSetup: false,
		streaming: false,
		thresholdValue: 100,
		layers: {
			grid: true,
			frontiers: true,
			paths: true,
		},
		colors: {
			default: { r: 1, g: 1, b: 1 },
			unknown: { r: 0.68, g: 0.73, b: 0.78 },
			start: { r: 0, g: 1, b: 0 },
			finish: { r: 1, g: 0, b: 0 },
			wall: { r: 0.109, g: 0.109, b: 0.45 },
			visited: { r: 0.329, g: 0.27, b: 0.968 },
			path: { r: 1, g: 1, b: 0 },
			reserved: { r: 0.98, g: 0.5, b: 0.16 },
			frontier: { r: 0.02, g: 0.78, b: 0.95 },
			vehicle: { r: 0.95, g: 0.24, b: 0.35 },
		},
	}),
	computed: {
		simulationStore() {
			return simulationStore;
		},
		backendView() {
			return simulationStore.viewState;
		},
		displayGrid() {
			return this.backendView ? this.backendView.grid : this.grid;
		},
		displayRows() {
			return this.backendView ? this.backendView.rows : this.rows;
		},
		displayCols() {
			return this.backendView ? this.backendView.cols : this.cols;
		},
		displayVehicles() {
			return this.backendView ? this.backendView.vehicles : [];
		},
		displayFrontiers() {
			return this.backendView ? this.backendView.frontiers : [];
		},
		displayPathsByVehicle() {
			return this.backendView ? this.backendView.pathsByVehicle : {};
		},
		displayChangedCells() {
			return this.backendView ? this.backendView.changedCells || [] : [];
		},
		obstacleCount() {
			if (!this.displayGrid) return 0;
			return this.displayGrid.reduce(
				(total, row) => total + row.filter((node) => node.status === "wall").length,
				0
			);
		},
		backendRuntime() {
			return this.backendView && this.backendView.runtime ? this.backendView.runtime : {};
		},
		backendStatus() {
			return (this.backendView && this.backendView.systemStatus) || "STOPPED";
		},
		backendStatusLabel() {
			return STATUS_NAMES[this.backendStatus] || this.backendStatus;
		},
		policyOptions() {
			const options = this.backendRuntime.policies || DEFAULT_POLICIES;
			return options.map((item) => ({
				...item,
				name: POLICY_NAMES[item.id] || item.name || item.id,
			}));
		},
		navigatorOptions() {
			const options = this.backendRuntime.navigatorAlgorithms || DEFAULT_NAVIGATORS;
			return options.map((item) => ({
				...item,
				name: NAVIGATOR_NAMES[item.id] || item.name || item.id,
			}));
		},
		vehicleSkinOptions() {
			return VEHICLE_SKINS;
		},
	},
	watch: {
		backendRuntime: {
			deep: true,
			handler() {
				this.syncBackendControls();
			},
		},
	},
	created() {
		this.start.gridId = this.start.row * this.cols + this.start.col;
		this.finish.gridId = this.finish.row * this.cols + this.finish.col;
	},
	beforeDestroy() {
		if (this.backendSocket) this.backendSocket.close();
	},
	methods: {
		onGroundInitialized(ground) {
			this.ground = ground;
			this.initBackend();
		},
		async initBackend() {
			if (this.backendInitialized) return;
			this.backendInitialized = true;
			try {
				setLoading(true);
				const snapshot = await fetchState();
				this.applyBackendSnapshot(snapshot);
				this.backendSocket = createSimulationSocket({
					onSnapshot: this.applyBackendSnapshot,
					onOpen: () => setConnected(true),
					onClose: () => setConnected(false),
					onError: this.reportBackendError,
				});
			} catch (error) {
				this.reportBackendError(error);
			} finally {
				setLoading(false);
			}
		},
		applyBackendSnapshot(snapshot) {
			const previousGrid = this.backendView && this.backendView.grid ? this.backendView.grid : this.grid;
			applySnapshot(snapshot, previousGrid);
			this.syncBackendControls();
		},
		syncBackendControls() {
			const runtime = this.backendRuntime;
			if (runtime.policy) this.backendControls.policy = runtime.policy;
			if (runtime.navigatorAlgorithm) {
				this.backendControls.navigatorAlgorithm = runtime.navigatorAlgorithm;
			}
			if (runtime.vehicleDeployment && !this.deploymentDirty) {
				this.backendControls.vehicleCount = runtime.vehicleDeployment.count || 8;
			}
			if (!this.mapConfigDirty && runtime.map) {
				this.backendControls.mapWidth = runtime.map.width || this.displayCols || 50;
				this.backendControls.mapHeight = runtime.map.height || this.displayRows || 50;
				this.backendControls.chunkSize = runtime.map.chunkSize || 10;
			} else if (!this.mapConfigDirty && this.backendView) {
				this.backendControls.mapWidth = this.backendView.cols || 50;
				this.backendControls.mapHeight = this.backendView.rows || 50;
			}
			const maxObstacles = Math.max(0, this.backendControls.mapWidth * this.backendControls.mapHeight - 1);
			if (Number(this.backendControls.obstacleCount || 0) > maxObstacles) {
				this.backendControls.obstacleCount = maxObstacles;
			}
		},
		reportBackendError(error) {
			setError(error);
			if (this.$refs.info && this.$refs.info.error) {
				this.$refs.info.error({
					heading: "后端连接",
					text: String(error.message || error),
				});
			}
		},
		async runBackendAction(action) {
			try {
				this.backendBusy = true;
				setLoading(true);
				const result = await action();
				if (result && result.snapshot) {
					this.applyBackendSnapshot(result.snapshot);
				}
				const snapshot = await fetchState();
				this.applyBackendSnapshot(snapshot);
				setError(null);
			} catch (error) {
				this.reportBackendError(error);
			} finally {
				this.backendBusy = false;
				setLoading(false);
			}
		},
		vehiclePayload() {
			return {
				count: Math.max(1, Math.min(12, Number(this.backendControls.vehicleCount) || 8)),
				mode: "adjust",
			};
		},
		mapPayload() {
			return {
				width: Math.max(3, Math.min(128, Number(this.backendControls.mapWidth) || 50)),
				height: Math.max(3, Math.min(128, Number(this.backendControls.mapHeight) || 50)),
				chunkSize: Math.max(2, Math.min(64, Number(this.backendControls.chunkSize) || 10)),
			};
		},
		obstaclePayload() {
			const total = Math.max(0, this.displayRows * this.displayCols - 1);
			return {
				mode: "random",
				count: Math.max(0, Math.min(total, Number(this.backendControls.obstacleCount) || 0)),
				seed: Date.now(),
			};
		},
		async handleBackendStart() {
			this.runBackendAction(async () => {
				if (this.deploymentDirty) {
					await setVehicles(this.vehiclePayload());
					this.deploymentDirty = false;
				}
				return startSimulation({
					policy: this.backendControls.policy,
					navigatorAlgorithm: this.backendControls.navigatorAlgorithm,
				});
			});
		},
		handleBackendPause() {
			this.runBackendAction(() => pauseSimulation());
		},
		handleBackendResume() {
			this.runBackendAction(async () => {
				if (this.deploymentDirty) {
					await setVehicles(this.vehiclePayload());
					this.deploymentDirty = false;
				}
				return resumeSimulation();
			});
		},
		handleBackendStop() {
			this.runBackendAction(() => stopSimulation());
		},
		handleBackendReset() {
			this.obstacleEditMode = false;
			this.runBackendAction(() => resetSimulation());
		},
		handlePolicyChange() {
			this.runBackendAction(() => setPolicy(this.backendControls.policy));
		},
		handleNavigatorChange() {
			this.runBackendAction(() => setNavigatorAlgorithm(this.backendControls.navigatorAlgorithm));
		},
		async handleVehiclesApply() {
			try {
				this.backendBusy = true;
				setLoading(true);
				const result = await setVehicles(this.vehiclePayload());
				if (result && result.snapshot) {
					this.applyBackendSnapshot(result.snapshot);
				}
				this.deploymentDirty = false;
				this.syncBackendControls();
				setError(null);
			} catch (error) {
				this.reportBackendError(error);
			} finally {
				this.backendBusy = false;
				setLoading(false);
			}
		},
		async handleMapApply() {
			try {
				this.backendBusy = true;
				setLoading(true);
				const result = await setMap(this.mapPayload());
				this.deploymentDirty = false;
				this.mapConfigDirty = false;
				this.obstacleEditMode = false;
				if (result && result.snapshot) {
					this.applyBackendSnapshot(result.snapshot);
				}
				this.syncBackendControls();
				setError(null);
			} catch (error) {
				this.reportBackendError(error);
			} finally {
				this.backendBusy = false;
				setLoading(false);
			}
		},
		async handleManualObstacles() {
			if (this.obstacleEditMode) {
				this.finishManualObstacles();
				return;
			}
			await this.applyObstacleDeployment({ mode: "manual" });
		},
		finishManualObstacles() {
			this.obstacleEditMode = false;
			this.resetObstaclePaint();
			if (this.$refs.info && this.$refs.info.alert) {
				this.$refs.info.alert({
					heading: "障碍设置",
					text: "手动障碍设置已结束，地图已保留当前障碍。",
				});
			}
		},
		async handleRandomObstacles() {
			await this.applyObstacleDeployment(this.obstaclePayload());
		},
		async applyObstacleDeployment(payload) {
			try {
				this.backendBusy = true;
				setLoading(true);
				const result = await setObstacles(payload);
				this.obstacleEditMode = payload.mode === "manual";
				let snapshot = result && result.snapshot;
				if (this.deploymentDirty) {
					const vehicleResult = await setVehicles(this.vehiclePayload());
					this.deploymentDirty = false;
					snapshot = vehicleResult && vehicleResult.snapshot ? vehicleResult.snapshot : snapshot;
				}
				if (snapshot) {
					this.applyBackendSnapshot(snapshot);
				}
				setError(null);
				if (this.$refs.info && this.$refs.info.alert) {
					this.$refs.info.alert({
						heading: "障碍部署",
						text: this.obstacleEditMode
							? "手动障碍已开启，点击地图格子可添加或移除障碍。"
							: "随机障碍已生成。",
					});
				}
			} catch (error) {
				this.reportBackendError(error);
			} finally {
				this.backendBusy = false;
				setLoading(false);
			}
		},
		async handleBackendGridClick(node) {
			if (this.obstacleEditMode) {
				return;
			}
		},
		handleBackendGridPaint(node) {
			if (!this.obstacleEditMode || this.backendStatus !== "STOPPED" || this.backendBusy || !node) return;
			const key = `${node.col},${node.row}`;
			if (this.obstaclePaint.seen[key]) return;
			if (this.obstaclePaint.blocked === null) {
				this.obstaclePaint.blocked = node.status !== "wall";
			}
			const blocked = this.obstaclePaint.blocked;
			if ((node.status === "wall") === blocked) {
				this.$set(this.obstaclePaint.seen, key, true);
				return;
			}
			this.$set(this.obstaclePaint.seen, key, true);
			this.obstaclePaint.cells.push({ x: node.col, y: node.row, blocked });
			node.status = blocked ? "wall" : "unknown";
			if (this.$refs.visualizer && this.$refs.visualizer.updateNode) {
				this.$refs.visualizer.updateNode(node, true);
			}
		},
		async flushObstaclePaint() {
			if (!this.obstaclePaint.cells.length) {
				this.resetObstaclePaint();
				return;
			}
			const cells = this.obstaclePaint.cells.slice();
			this.resetObstaclePaint();
			try {
				this.backendBusy = true;
				setLoading(true);
				const result = await setObstacleCells({ cells });
				if (result && result.snapshot) {
					this.applyBackendSnapshot(result.snapshot);
				}
				if (result && result.deployment) {
					this.deploymentDirty = false;
				}
				setError(null);
			} catch (error) {
				this.reportBackendError(error);
				try {
					this.applyBackendSnapshot(await fetchState());
				} catch (snapshotError) {
					this.reportBackendError(snapshotError);
				}
			} finally {
				this.backendBusy = false;
				setLoading(false);
			}
		},
		resetObstaclePaint() {
			this.obstaclePaint.blocked = null;
			this.obstaclePaint.cells = [];
			this.obstaclePaint.seen = {};
		},
		async toggleObstacleNode(node) {
			if (this.backendStatus !== "STOPPED" || this.backendBusy) return;
			try {
				this.backendBusy = true;
				setLoading(true);
				const result = await setObstacleCell({ x: node.col, y: node.row });
				if (result && result.snapshot) {
					this.applyBackendSnapshot(result.snapshot);
				}
				setError(null);
			} catch (error) {
				this.reportBackendError(error);
			} finally {
				this.backendBusy = false;
				setLoading(false);
			}
		},
		switchControl() {
			if (this.controlType == "Orbit") {
				this.controlType = "PointerLock";
				setTimeout(() => {
					if (this.$refs.info) {
						this.$refs.info.alert({
							heading: "第一人称视角",
							text: "点击画布启用第一人称控制，按 Esc 键退出。",
						});
					}
				}, 600);
			} else {
				this.controlType = "Orbit";
				if (this.$refs.info) this.$refs.info.resetToLegends();
			}
		},
		showInfoError(text) {
			if (this.$refs.info && this.$refs.info.error) {
				this.$refs.info.error({ heading: "提示", text });
			}
		},
		clearFocus() {
			const headers = document.getElementsByClassName("header");
			if (headers[0]) headers[0].click();
		},
	},
};
</script>

<style lang="scss">
@import "@/scss/variables.scss";

.pathfinding-visualizer {
	width: 100vw;
	height: 100vh;
	overflow: hidden;

	.header {
		position: absolute;
		top: 0;
		left: 0;
		width: 100%;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 2px;
		transition: all 500ms ease-out;
		z-index: 3;

		&::before {
			content: "";
			position: absolute;
			top: -100%;
			left: 0;
			height: 100%;
			width: 100%;
			box-shadow: 1px 10px 50px rgba(0, 0, 0, 1);
			z-index: -1;
		}

		select,
		.vehicle-count,
		.obstacle-count,
		.map-size {
			height: 40px;
			background: white;
			color: rgb(0, 0, 0);
			padding: 8px;
			margin: 2px;
			border-radius: 3px;
			border: none;
			width: fit-content;
			max-width: 190px;
		}

		.vehicle-count,
		.obstacle-count,
		.map-size {
			width: 64px;
		}

		.vehicle-controls {
			display: inline-flex;
			align-items: center;
			gap: 2px;
			margin: 2px;

			.btn,
			.vehicle-count,
			.vehicle-skin-picker {
				margin: 0;
			}
		}

		.vehicle-skin-picker {
			display: inline-flex;
			align-items: center;
			gap: 6px;
			height: 40px;
			padding: 0 0 0 10px;
			border-radius: 3px;
			background: rgba(255, 255, 255, 0.94);
			color: #172033;
			font-size: 12px;
			font-weight: 700;

			span {
				white-space: nowrap;
			}
		}

		.vehicle-skin {
			min-width: 122px;
			max-width: 148px;
			margin: 0;
		}
	}

	.backend-status,
	.obstacle-status,
	.backend-error {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		min-height: 40px;
		padding: 0 10px;
		margin: 2px;
		border-radius: 3px;
		background: rgba(255, 255, 255, 0.94);
		color: #172033;
		font-size: 12px;
		font-weight: 700;
	}

	.backend-error {
		position: absolute;
		left: 8px;
		top: 50px;
		z-index: 4;
		max-width: min(640px, calc(100vw - 16px));
		color: #8a1f11;
	}

	.dot {
		width: 9px;
		height: 9px;
		border-radius: 50%;
		background: #b3261e;

		&.online {
			background: #178a3b;
		}
	}

	.btn {
		margin: 2px;
		font-size: 0.7em;
		font-weight: 600;
		text-transform: uppercase;

		.lg {
			display: block;
		}

		.sm {
			display: none;
		}
	}

	.btn-controls {
		top: 60px;
	}

	.btn-camera {
		top: 115px;
	}

	.layer-controls {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		min-height: 40px;
		padding: 0 10px;
		margin: 2px;
		border-radius: 3px;
		background: rgba(255, 255, 255, 0.94);
		color: #172033;
		font-size: 12px;
		font-weight: 700;

		label {
			display: inline-flex;
			align-items: center;
			gap: 4px;
			white-space: nowrap;
			cursor: pointer;
		}

		input {
			width: 16px;
			height: 16px;
			margin: 0;
			accent-color: $primary;
		}
	}

	@media (max-width: 792px) {
		.btn {
			.lg {
				display: none;
			}

			.sm {
				display: block;
				font-size: 0.7em;
			}

			&.hover {
				&:hover {
					width: 55px;
				}
			}
		}

		.btn-camera {
			top: 115px;
		}

		.btn-controls {
			display: none;
		}

		.header {
			select,
			.vehicle-count,
			.obstacle-count {
				padding: 2px;
				font-size: 0.7em;
				max-width: 120px;
			}

			.vehicle-controls {
				gap: 1px;
			}

			.vehicle-skin-picker {
				padding-left: 6px;
				font-size: 0.7em;
			}

			.vehicle-skin {
				min-width: 88px;
				max-width: 98px;
			}
		}

		.layer-controls {
			gap: 6px;
			padding: 0 6px;
			font-size: 11px;
		}
	}

	.slide-enter-active,
	.slide-leave-active {
		transition: all 500ms ease-in-out;
	}

	.slide-leave-active {
		position: absolute;
	}

	.slide-enter,
	.slide-leave-to {
		opacity: 0;
		transform: translateY(-50%);
	}

	.slide-move {
		transition: all 500ms ease-in-out;
	}
}
</style>
