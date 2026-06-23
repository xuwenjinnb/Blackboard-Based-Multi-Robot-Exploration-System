<template>
	<div id="visualizer" @click="controlType == 'PointerLock' ? controls.lock() : clearFocus">
		<script type="x-shader/x-vertex" id="vertexShader">
			varying vec3 vWorldPosition;

			void main() {
				vec4 worldPosition = modelMatrix * vec4( position, 1.0 );
				vWorldPosition = worldPosition.xyz;
				gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
			}
		</script>
		<script type="x-shader/x-fragment" id="fragmentShader">
			uniform vec3 topColor;
			uniform vec3 bottomColor;
			uniform float offset;
			uniform float exponent;

			varying vec3 vWorldPosition;

			void main() {
				float h = normalize( vWorldPosition + offset ).y;
				gl_FragColor = vec4( mix( bottomColor, topColor, max( pow( max( h , 0.0), exponent ), 0.0 ) ), 1.0 );
			}
		</script>
	</div>
</template>

<script>
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { PointerLockControls } from "three/examples/jsm/controls/PointerLockControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import TWEEN from "@tweenjs/tween.js";
import Stats from "three/examples/jsm/libs/stats.module.js";

import { API_BASE_URL } from "@/config/backend";
import { tweenToColor } from "./algorithms/helpers.js";

export default {
	props: [
		"nodeDimensions",
		"grid",
		"rows",
		"cols",
		"start",
		"finish",
		"visualizerState",
		"colors",
		"controlType",
		"worldSetup",
		"selectedAlgorithm",
		"streaming",
		"thresholdValue",
		"backendMode",
		"vehicles",
		"frontiers",
		"pathsByVehicle",
		"showGrid",
		"showFrontiers",
		"showPaths",
		"obstacleEditMode",
		"backendChangedCells",
		"vehicleModel"
	],
	data: () => ({
		scene: null,
		camera: null,
		cameraY: 0,
		defaultCameraY: 250,
		renderer: null,
		pointerLock: {
			moveForward: false,
			moveBackward: false,
			moveLeft: false,
			moveRight: false,
			velocity: null,
			direction: null,
			prevTime: null,
		},
		controls: null,
		orbitControls: null,
		pointerLockControls: null,
		raycaster: null,
		ambientLight: null,
		hemisphereLight: null,
		directionalLight: null,
		ground: null,
		gridHelper: null,
		wallGeomtery: null,
		wallMaterials: [],
		walls: {},
		vehicleMeshes: {},
		vehicleModelTemplate: null,
		vehicleModelTemplateName: "",
		vehicleModelLoadToken: 0,
		frontierMeshes: {},
		pathMeshes: {},
		overlayMaterials: {},
		nodeWatchers: [],
		vehicleMeshSignature: "",
		frontierMeshSignature: "",
		pathMeshSignature: "",
		mapResizePending: false,
		wallTextures: [
			{
				path: "building1.png",
				repeatY: 1,
			},
			{
				path: "building2.png",
				repeatY: 2,
			},
			{
				path: "building3.png",
				repeatY: 3,
			},
		],
		down: false,
		moved: false,
		currentEvent: null,
		mouse: null,
		intersectedNode: null,
		paintingObstacle: false,
		paintControlsEnabled: null,
		clock: null,
		stats: null,
		// Device cam
		videoCanvas: null,
		video: null,
		animationFrameId: null,
		destroyed: false
	}),
	computed: {
		clickableObjects() {
			let objects = [];
			objects.push(this.ground);
			for (let id of Object.keys(this.walls)) {
				if (this.walls[id].visible) {
					objects.push(this.walls[id]);
				}
			}
			return objects;
		},
		collidableObjects() {
			let objects = [];
			for (let id of Object.keys(this.walls)) {
				if (this.walls[id].visible) {
					objects.push(this.walls[id]);
				}
			}
			return objects;
		},
		obstaclePaintingEnabled() {
			return this.backendMode
				&& this.obstacleEditMode
				&& this.$listeners.paintEvent
				&& !this.worldSetup
				&& this.controlType != "PointerLock";
		}
	},
	watch: {
		controlType: function(newVal, oldVal) {
			this.setControls();
		},
		vehicleModel: function(newVal, oldVal) {
			if (newVal !== oldVal) this.loadVehicleModel();
		},
		backendChangedCells: {
			handler(cells) {
				if (!this.backendMode || !cells || !cells.length) return;
				this.updateChangedGridCells(cells);
			}
		},
		worldSetup: function(newVal, oldVal) {
			if (newVal) {
				TWEEN.removeAll();
				new TWEEN.Tween(this.camera.position)
					.to({ x: 0, y: this.cameraY - 30, z: 0 }, 500)
					.easing(TWEEN.Easing.Exponential.Out)
					.onUpdate(() => {
						this.camera.lookAt(this.scene.position);
					})
					.onComplete(() => {
						this.controls.enableRotate = false;
						let lookDirection = new THREE.Vector3();
						this.camera.getWorldDirection(lookDirection);
						this.controls.target
							.copy(this.camera.position)
							.add(lookDirection.multiplyScalar(this.cameraY - 30));
					})
					.start();
				new TWEEN.Tween(this.camera.rotation)
					.to({ y: 0, z: 0 }, 500)
					.easing(TWEEN.Easing.Exponential.Out)
					.start();
			} else {
				new TWEEN.Tween(this.camera.position)
					.to({ y: this.cameraY }, 500)
					.easing(TWEEN.Easing.Exponential.Out)
					.onComplete(() => {
						this.controls.enableRotate = true;
						this.controls.update();
					})
					.start();
			}
		},
		streaming: function(newVal, oldVal) {
			if(!newVal) {
				for(let i=0; i<this.rows; i++) {
					for(let j=0; j<this.cols; j++) {
						if (this.grid[i] && this.grid[i][j]) {
							this.updateNode(this.grid[i][j], this.backendMode);
						}
					}
				}
			}
		},
		rows: function(newVal, oldVal) {
			if (newVal !== oldVal) this.scheduleMapGeometryRebuild();
		},
		cols: function(newVal, oldVal) {
			if (newVal !== oldVal) this.scheduleMapGeometryRebuild();
		},
		grid: {
			handler() {
				this.$nextTick(() => {
					if (!this.groundGeometryMatchesMap()) {
						this.scheduleMapGeometryRebuild();
						return;
					}
					if (!this.backendMode) {
						this.refreshGridColors();
					}
				});
			}
		},
		vehicles: {
			deep: true,
			handler() {
				this.updateVehicleMeshes();
			}
		},
		frontiers: {
			deep: true,
			handler() {
				this.updateFrontierMeshes();
			}
		},
		pathsByVehicle: {
			deep: true,
			handler() {
				this.updatePathMeshes();
			}
		},
		showGrid() {
			this.updateLayerVisibility();
		},
		showFrontiers() {
			this.updateLayerVisibility();
		},
		showPaths() {
			this.updateLayerVisibility();
		}
	},
	created() {
		this.cameraY = this.defaultCameraY;
	},
	mounted() {
		this.init();
		
		this.videoCanvas = document.querySelector('#video-canvas');
		this.video = document.querySelector('video');
	},
	beforeDestroy() {
		this.destroyed = true;
		if (this.animationFrameId) cancelAnimationFrame(this.animationFrameId);
		window.removeEventListener("resize", this.resizeHandler);
		document.removeEventListener("keydown", this.onKeyDown, false);
		document.removeEventListener("keyup", this.onKeyUp, false);
		this.clearNodeWatchers();
		this.clearWalls();
		Object.keys(this.vehicleMeshes).forEach((id) => this.disposeObject(this.vehicleMeshes[id]));
		Object.keys(this.frontierMeshes).forEach((id) => this.disposeObject(this.frontierMeshes[id]));
		Object.keys(this.pathMeshes).forEach((id) => this.disposeObject(this.pathMeshes[id]));
	},
	methods: {
		init() {
			let width = window.innerWidth,
				height = window.innerHeight;

			//Scene
			this.scene = new THREE.Scene();
			this.scene.background = new THREE.Color(0xbbd6ff);
			this.scene.fog = new THREE.Fog(0xffffff, 0, 750);

			//Camera
			this.camera = new THREE.PerspectiveCamera(60, width / height, 1, 5000);
			this.camera.position.y = this.cameraY + 2000;
			this.camera.position.x = -500;
			this.camera.position.z = 500;
			// var helper = new THREE.CameraHelper(this.camera);
			// this.scene.add(helper);

			//Renderer
			this.renderer = new THREE.WebGLRenderer({ antialias: true });
			this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
			this.renderer.setSize(width, height);
			this.renderer.shadowMap.enabled = false;
			// this.renderer.shadowMap.type = THREE.BasicShadowMap;
			document.getElementById("visualizer").appendChild(this.renderer.domElement);

			// Controls
			this.addControls();
			this.setControls(true);

			// Raycaster
			this.raycaster = new THREE.Raycaster();

			// Ground
			let vm = this;
			let groundGeometry = this.createGroundGeometry();
			let loader = new THREE.TextureLoader();
			loader.load(
				require("@/assets/textures/ground.png"),
				function(texture) {
					texture.wrapS = THREE.RepeatWrapping;
					texture.wrapT = THREE.RepeatWrapping;
					texture.repeat.x = vm.rows;
					texture.repeat.y = vm.cols;
					var groundMaterial = new THREE.MeshLambertMaterial({
						map: texture,
						side: THREE.FrontSide,
						vertexColors: THREE.FaceColors,
					});
					vm.ground = new THREE.Mesh(groundGeometry, groundMaterial);
					vm.ground.receiveShadow = true;
					vm.ground.position.y = 0.02;
					vm.scene.add(vm.ground);
					vm.initGrid();
					vm.refreshGridColors();
					vm.updateVehicleMeshes();
					vm.updateFrontierMeshes();
					vm.updatePathMeshes();
					vm.$emit("groundInitialized", vm.ground);
				},
				undefined,
				function(error) {
					console.log(error);
				}
			);
			let fakeGroundGeometry = new THREE.PlaneGeometry(1000, 1000, this.cols, this.rows);
			fakeGroundGeometry.rotateX(-Math.PI / 2);
			var fakeGroundMaterial = new THREE.MeshLambertMaterial({
				// color: 0x87775d,
				color: 0xBBC2D0,
				side: THREE.FrontSide,
			});
			let fakeGround = new THREE.Mesh(fakeGroundGeometry, fakeGroundMaterial);
			this.scene.add(fakeGround);

			//Grid helper
			this.gridHelper = this.createGridHelper();
			this.scene.add(this.gridHelper);
			this.updateLayerVisibility();

			// Wall
			// let wallHeight = this.nodeDimensions.width * 2 + Math.random() * this.nodeDimensions.width * 3;
			let wallHeight = this.nodeDimensions.height * 2;
			this.wallGeomtery = new THREE.BoxBufferGeometry(
				this.nodeDimensions.width,
				wallHeight,
				this.nodeDimensions.height
			);
			this.wallMaterials.push(
				new THREE.MeshPhongMaterial({
					color: new THREE.Color(this.colors.wall.r, this.colors.wall.g, this.colors.wall.b),
				})
			);
			for (let tex of this.wallTextures) {
				loader.load(
					require("@/assets/textures/" + tex.path),
					function(texture) {
						texture.wrapT = THREE.RepeatWrapping;
						texture.repeat.y = tex.repeatY;
						vm.wallMaterials.push(new THREE.MeshLambertMaterial({ map: texture }));
					},
					undefined,
					function(error) {
						console.log(error);
					}
				);
			}
			this.initOverlayMaterials();

			// Ambient Light
			this.ambientLight = new THREE.AmbientLight(0xffffff, 1);
			this.scene.add(this.ambientLight);

			// LIGHTS
			this.hemisphereLight = new THREE.HemisphereLight(0xffffff, 0xffffff, 0.1);
			this.hemisphereLight.color.setHSL(0.6, 1, 0.6);
			this.hemisphereLight.groundColor.setHex(0x87775d);
			this.hemisphereLight.position.set(0, 5, 0);
			this.scene.add(this.hemisphereLight);

			// let hemiLightHelper = new THREE.HemisphereLightHelper(this.hemisphereLight, 10);
			// this.scene.add(hemiLightHelper);

			this.directionalLight = new THREE.DirectionalLight(0xffffff, 0.5);
			this.directionalLight.color.setHSL(0.1, 1, 0.95);
			this.directionalLight.position.set(-1, 1.75, 1);
			this.directionalLight.position.multiplyScalar(70);
			this.scene.add(this.directionalLight);

			this.directionalLight.castShadow = true;
			this.directionalLight.shadow.mapSize.width = 2048;
			this.directionalLight.shadow.mapSize.height = 2048;

			var d = 200;
			this.directionalLight.shadow.camera.left = -d;
			this.directionalLight.shadow.camera.right = d;
			this.directionalLight.shadow.camera.top = d;
			this.directionalLight.shadow.camera.bottom = -d;
			this.directionalLight.shadow.camera.far = 350;

			// SKYDOME
			var vertexShader = document.getElementById("vertexShader").textContent;
			var fragmentShader = document.getElementById("fragmentShader").textContent;
			var uniforms = {
				topColor: { value: new THREE.Color(0x0077ff) },
				bottomColor: { value: new THREE.Color(0xffffff) },
				offset: { value: 33 },
				exponent: { value: 0.6 },
			};
			uniforms["topColor"].value.copy(this.hemisphereLight.color);

			this.scene.fog.color.copy(uniforms["bottomColor"].value);
			var skyGeo = new THREE.SphereBufferGeometry(1000, 32, 15);
			var skyMat = new THREE.ShaderMaterial({
				uniforms: uniforms,
				vertexShader: vertexShader,
				fragmentShader: fragmentShader,
				side: THREE.BackSide,
			});
			var sky = new THREE.Mesh(skyGeo, skyMat);
			this.scene.add(sky);

			// Stats
			this.stats = new Stats();
			this.stats.dom.style.top = "auto";
			this.stats.dom.style.bottom = '5px';
			this.stats.dom.style.left = '3px';
			document.getElementById("visualizer").appendChild(this.stats.dom);

			//Resize handler
			window.addEventListener("resize", this.resizeHandler);
			this.renderer.domElement.addEventListener("mousedown", this.onMouseDown, true);
			this.renderer.domElement.addEventListener("touchstart", this.onMouseDown, true);
			this.renderer.domElement.addEventListener("mousemove", this.onMouseMove, true);
			this.renderer.domElement.addEventListener("touchmove", this.onMouseMove, true);
			this.renderer.domElement.addEventListener("mouseup", this.onMouseup, true);
			this.renderer.domElement.addEventListener("mouseleave", this.onMouseLeave, true);
			this.renderer.domElement.addEventListener("touchend", this.onMouseup, true);

			// Setting hover handler
			this.mouse = new THREE.Vector2();

			this.loadVehicleModel();
			this.renderLoop();
		},

		renderLoop() {
			if (this.destroyed) return;
			this.animationFrameId = requestAnimationFrame(() => this.renderLoop());
			if (this.controlType == "PointerLock") {
				var delta = this.clock.getDelta();
				this.animatePlayer(delta);
			}
			if (this.worldSetup) {
				this.hoverObjectLoop();
				if(this.streaming) {
					this.deviceCamLoop();
				}
			}
			this.renderer.render(this.scene, this.camera);
			TWEEN.update();
			this.stats.update();
		},

		initOverlayMaterials() {
			this.overlayMaterials.frontierOpen = new THREE.MeshPhongMaterial({
				color: 0x02c7f2,
				emissive: 0x014d66,
				transparent: true,
				opacity: 0.9,
			});
			this.overlayMaterials.frontierAssigned = new THREE.MeshPhongMaterial({
				color: 0xffa33a,
				emissive: 0x663000,
				transparent: true,
				opacity: 0.9,
			});
		},

		createGroundGeometry() {
			const gridWidth = this.cols * this.nodeDimensions.width;
			const gridHeight = this.rows * this.nodeDimensions.height;
			const geometry = new THREE.PlaneGeometry(gridWidth, gridHeight, this.cols, this.rows);
			geometry.rotateX(-Math.PI / 2);
			return geometry;
		},

		groundGeometryMatchesMap() {
			if (!this.ground || !this.ground.geometry) return false;
			const params = this.ground.geometry.parameters || {};
			const gridWidth = this.cols * this.nodeDimensions.width;
			const gridHeight = this.rows * this.nodeDimensions.height;
			return (
				Number(params.width) === Number(gridWidth) &&
				Number(params.height) === Number(gridHeight) &&
				Number(params.widthSegments) === Number(this.cols) &&
				Number(params.heightSegments) === Number(this.rows)
			);
		},

		scheduleMapGeometryRebuild() {
			if (this.mapResizePending) return;
			this.mapResizePending = true;
			this.$nextTick(() => {
				this.mapResizePending = false;
				this.rebuildMapGeometry();
			});
		},

		rebuildMapGeometry() {
			if (!this.scene || !this.ground) return;

			TWEEN.removeAll();
			this.down = false;
			this.intersectedNode = null;

			this.clearNodeWatchers();
			this.clearWalls();
			this.clearMeshMap(this.frontierMeshes);
			this.clearMeshMap(this.pathMeshes);

			const oldGeometry = this.ground.geometry;
			this.ground.geometry = this.createGroundGeometry();
			if (oldGeometry) oldGeometry.dispose();
			this.updateGroundTextureRepeat();

			if (this.gridHelper) {
				this.disposeObject(this.gridHelper);
			}
			this.gridHelper = this.createGridHelper();
			this.scene.add(this.gridHelper);

			this.initGrid();
			this.refreshGridColors();
			this.rebuildVehicleMeshes();
			this.updateFrontierMeshes();
			this.updatePathMeshes();
			this.updateLayerVisibility();
		},

		updateGroundTextureRepeat() {
			const texture = this.ground && this.ground.material && this.ground.material.map;
			if (!texture) return;
			texture.repeat.x = this.rows;
			texture.repeat.y = this.cols;
			texture.needsUpdate = true;
		},

		clearNodeWatchers() {
			for (const unwatch of this.nodeWatchers) {
				if (typeof unwatch === "function") unwatch();
			}
			this.nodeWatchers = [];
		},

		clearWalls() {
			for (const id of Object.keys(this.walls)) {
				const wall = this.walls[id];
				if (wall && wall.parent) wall.parent.remove(wall);
				this.$delete(this.walls, id);
			}
		},

		clearMeshMap(meshMap) {
			for (const id of Object.keys(meshMap)) {
				this.disposeObject(meshMap[id]);
				this.$delete(meshMap, id);
			}
		},

		refreshGridColors() {
			if (!this.ground || !this.grid || !this.grid.length) return;
			for (let row = 0; row < this.rows; row++) {
				for (let col = 0; col < this.cols; col++) {
					if (this.grid[row] && this.grid[row][col]) {
						this.updateNode(this.grid[row][col], this.backendMode || this.streaming);
					}
				}
			}
		},
		updateChangedGridCells(cells) {
			if (!this.ground || !this.grid || !this.grid.length) return;
			for (const cell of cells || []) {
				const row = Number(cell.row);
				const col = Number(cell.col);
				if (this.grid[row] && this.grid[row][col]) {
					this.updateNode(this.grid[row][col], true);
				}
			}
		},

		createGridHelper() {
			const gridWidth = this.cols * this.nodeDimensions.width;
			const gridHeight = this.rows * this.nodeDimensions.height;
			const points = [];
			for (let col = 0; col <= this.cols; col++) {
				const x = -gridWidth / 2 + col * this.nodeDimensions.width;
				points.push(new THREE.Vector3(x, 0.04, -gridHeight / 2));
				points.push(new THREE.Vector3(x, 0.04, gridHeight / 2));
			}
			for (let row = 0; row <= this.rows; row++) {
				const z = -gridHeight / 2 + row * this.nodeDimensions.height;
				points.push(new THREE.Vector3(-gridWidth / 2, 0.04, z));
				points.push(new THREE.Vector3(gridWidth / 2, 0.04, z));
			}
			const geometry = new THREE.BufferGeometry().setFromPoints(points);
			const material = new THREE.LineBasicMaterial({
				color: 0x5c78bd,
				transparent: true,
				opacity: 0.78,
			});
			return new THREE.LineSegments(geometry, material);
		},

		gridToWorld(row, col, y = 1) {
			let gridWidth = this.cols * this.nodeDimensions.width;
			let gridHeight = this.rows * this.nodeDimensions.height;
			return {
				x: -gridWidth / 2 + this.nodeDimensions.width / 2 + col * this.nodeDimensions.width,
				y,
				z: -gridHeight / 2 + this.nodeDimensions.height / 2 + row * this.nodeDimensions.height,
			};
		},

		vehicleColor(vehicleId) {
			const palette = [0xe63946, 0x2a9d8f, 0xf4a261, 0x6a4c93, 0x118ab2, 0x8ac926];
			let hash = 0;
			for (let i = 0; i < String(vehicleId).length; i++) {
				hash = (hash * 31 + String(vehicleId).charCodeAt(i)) >>> 0;
			}
			return palette[hash % palette.length];
		},

		headingToRotation(heading) {
			const normalized = Number(heading || 0);
			return -normalized * Math.PI / 180 + Math.PI / 2;
		},

		disposeObject(object) {
			if (!object) return;
			if (object.parent) object.parent.remove(object);
			const sharedMaterials = Object.values(this.overlayMaterials);
			object.traverse((child) => {
				if (child.geometry) child.geometry.dispose();
				if (
					child.material &&
					!Array.isArray(child.material) &&
					!sharedMaterials.includes(child.material)
				) {
					child.material.dispose();
				}
				if (Array.isArray(child.material)) {
					child.material.forEach((material) => {
						if (!sharedMaterials.includes(material)) material.dispose();
					});
				}
			});
		},

		updateVehicleMeshes() {
			if (!this.scene) return;
			const signature = this.vehicleSignature();
			if (signature === this.vehicleMeshSignature) return;
			this.vehicleMeshSignature = signature;
			const activeIds = new Set();
			for (const vehicle of this.vehicles || []) {
				if (!vehicle || vehicle.id == null) continue;
				activeIds.add(vehicle.id);
				let mesh = this.vehicleMeshes[vehicle.id];
				if (!mesh) {
					mesh = this.createVehicleMesh(vehicle);
					this.$set(this.vehicleMeshes, vehicle.id, mesh);
					this.scene.add(mesh);
				}
				const position = this.gridToWorld(vehicle.row, vehicle.col, 0.12);
				mesh.position.set(position.x, position.y, position.z);
				mesh.rotation.y =
					this.headingToRotation(vehicle.heading) +
					(mesh.userData.headingOffset || 0);
				mesh.userData.vehicle = vehicle;
			}
			for (const id of Object.keys(this.vehicleMeshes)) {
				if (!activeIds.has(id)) {
					this.disposeObject(this.vehicleMeshes[id]);
					this.$delete(this.vehicleMeshes, id);
				}
			}
		},

		loadVehicleModel() {
			const modelName = this.normalizedVehicleModelName();
			if (this.vehicleModelTemplate && this.vehicleModelTemplateName === modelName) return;

			const loader = new GLTFLoader();
			const loadToken = ++this.vehicleModelLoadToken;
			const modelUrl =
				`${API_BASE_URL}/static/assets/kenney-car-kit/Models/GLB%20format/${encodeURIComponent(modelName)}.glb`;

			loader.load(
				modelUrl,
				(gltf) => {
					if (this.destroyed || loadToken !== this.vehicleModelLoadToken) return;
					this.vehicleModelTemplate = gltf.scene;
					this.vehicleModelTemplateName = modelName;
					this.rebuildVehicleMeshes();
				},
				undefined,
				(error) => {
					if (this.destroyed || loadToken !== this.vehicleModelLoadToken) return;
					this.vehicleModelTemplate = null;
					this.vehicleModelTemplateName = "";
					this.rebuildVehicleMeshes();
					console.error("小车模型加载失败，将继续使用简易模型。", error);
				}
			);
		},

		normalizedVehicleModelName() {
			const modelName = String(this.vehicleModel || "sedan").replace(/[^a-z0-9-]/gi, "");
			return modelName || "sedan";
		},

		rebuildVehicleMeshes() {
			this.vehicleMeshSignature = "";
			for (const id of Object.keys(this.vehicleMeshes)) {
				this.disposeObject(this.vehicleMeshes[id]);
				this.$delete(this.vehicleMeshes, id);
			}
			this.updateVehicleMeshes();
		},

		createVehicleMesh(vehicle) {
			if (this.vehicleModelTemplate) {
				return this.createLoadedVehicleMesh();
			}
			return this.createFallbackVehicleMesh(vehicle);
		},

		createLoadedVehicleMesh() {
			const group = new THREE.Group();
			const model = this.vehicleModelTemplate.clone(true);

			model.traverse((child) => {
				if (!child.isMesh) return;
				child.geometry = child.geometry.clone();
				if (Array.isArray(child.material)) {
					child.material = child.material.map((material) => material.clone());
				} else if (child.material) {
					child.material = child.material.clone();
				}
				this.normalizeVehicleMaterial(child.material);
				child.castShadow = false;
				child.receiveShadow = false;
			});

			const originalBox = new THREE.Box3().setFromObject(model);
			const originalSize = originalBox.getSize(new THREE.Vector3());
			const targetLength = this.nodeDimensions.width * 0.78;
			const longestSide = Math.max(originalSize.x, originalSize.z, 0.001);
			const scale = targetLength / longestSide;
			model.scale.setScalar(scale);

			const fittedBox = new THREE.Box3().setFromObject(model);
			const fittedCenter = fittedBox.getCenter(new THREE.Vector3());
			model.position.x -= fittedCenter.x;
			model.position.z -= fittedCenter.z;
			model.position.y -= fittedBox.min.y;

			group.name = "vehicle";
			group.userData.headingOffset = 0;
			group.add(model);
			return group;
		},

		normalizeVehicleMaterial(material) {
			const materials = Array.isArray(material) ? material : [material];
			for (const item of materials) {
				if (!item) continue;
				item.vertexColors = false;
				if (item.map) {
					item.map.encoding = THREE.sRGBEncoding;
					item.map.needsUpdate = true;
					if (item.color) item.color.setHex(0xffffff);
				} else if (item.color) {
					item.color.setHex(0xd94f35);
				}
				item.needsUpdate = true;
			}
		},

		createFallbackVehicleMesh(vehicle) {
			const color = this.vehicleColor(vehicle.id);
			const group = new THREE.Group();
			group.name = "vehicle";
			group.userData.headingOffset = 0;
			const body = new THREE.Mesh(
				new THREE.BoxBufferGeometry(
					this.nodeDimensions.width * 0.72,
					this.nodeDimensions.height * 0.32,
					this.nodeDimensions.height * 0.58
				),
				new THREE.MeshPhongMaterial({ color })
			);
			body.castShadow = false;
			body.receiveShadow = false;
			group.add(body);

			const nose = new THREE.Mesh(
				new THREE.ConeBufferGeometry(this.nodeDimensions.width * 0.18, this.nodeDimensions.width * 0.42, 16),
				new THREE.MeshPhongMaterial({ color: 0xffffff })
			);
			nose.rotation.x = Math.PI / 2;
			nose.position.z = -this.nodeDimensions.height * 0.42;
			group.add(nose);
			return group;
		},

		updateFrontierMeshes() {
			if (!this.scene) return;
			const signature = this.frontierSignature();
			if (signature === this.frontierMeshSignature) return;
			this.frontierMeshSignature = signature;
			const activeIds = new Set();
			for (const frontier of this.frontiers || []) {
				if (!frontier || frontier.id == null) continue;
				activeIds.add(frontier.id);
				let mesh = this.frontierMeshes[frontier.id];
				if (!mesh) {
					const material =
						frontier.status === "ASSIGNED"
							? this.overlayMaterials.frontierAssigned
							: this.overlayMaterials.frontierOpen;
					mesh = new THREE.Mesh(
						new THREE.CylinderBufferGeometry(
							this.nodeDimensions.width * 0.22,
							this.nodeDimensions.width * 0.22,
							0.7,
							18
						),
						material
					);
					mesh.name = "frontier";
					this.$set(this.frontierMeshes, frontier.id, mesh);
					this.scene.add(mesh);
				}
				mesh.material =
					frontier.status === "ASSIGNED"
						? this.overlayMaterials.frontierAssigned
						: this.overlayMaterials.frontierOpen;
				const position = this.gridToWorld(frontier.row, frontier.col, 1.1);
				mesh.position.set(position.x, position.y, position.z);
				mesh.visible = this.showFrontiers !== false;
			}
			for (const id of Object.keys(this.frontierMeshes)) {
				if (!activeIds.has(id)) {
					this.disposeObject(this.frontierMeshes[id]);
					this.$delete(this.frontierMeshes, id);
				}
			}
		},

		updatePathMeshes() {
			if (!this.scene) return;
			const signature = this.pathSignature();
			if (signature === this.pathMeshSignature) return;
			this.pathMeshSignature = signature;
			const activeIds = new Set();
			const paths = this.pathsByVehicle || {};
			for (const vehicleId of Object.keys(paths)) {
				const steps = paths[vehicleId] || [];
				if (steps.length < 2) continue;
				activeIds.add(vehicleId);
				const points = steps.map((step) => {
					const position = this.gridToWorld(step.row, step.col, 1.35);
					return new THREE.Vector3(position.x, position.y, position.z);
				});
				let line = this.pathMeshes[vehicleId];
				if (!line) {
					const material = new THREE.LineBasicMaterial({
						color: this.vehicleColor(vehicleId),
						linewidth: 3,
						transparent: true,
						opacity: 0.82,
					});
					line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), material);
					line.name = "vehicle-path";
					this.$set(this.pathMeshes, vehicleId, line);
					this.scene.add(line);
				} else {
					line.geometry.dispose();
					line.geometry = new THREE.BufferGeometry().setFromPoints(points);
				}
				line.visible = this.showPaths !== false;
			}
			for (const id of Object.keys(this.pathMeshes)) {
				if (!activeIds.has(id)) {
					this.disposeObject(this.pathMeshes[id]);
					this.$delete(this.pathMeshes, id);
				}
			}
		},

		updateLayerVisibility() {
			if (this.gridHelper) {
				this.gridHelper.visible = this.showGrid !== false;
			}
			Object.values(this.frontierMeshes).forEach((mesh) => {
				mesh.visible = this.showFrontiers !== false;
			});
			Object.values(this.pathMeshes).forEach((mesh) => {
				mesh.visible = this.showPaths !== false;
			});
		},
		vehicleSignature() {
			return (this.vehicles || [])
				.map((vehicle) => [
					vehicle.id,
					vehicle.row,
					vehicle.col,
					Number(vehicle.heading || 0).toFixed(1),
					vehicle.status || "",
				].join(":"))
				.sort()
				.join("|");
		},
		frontierSignature() {
			return (this.frontiers || [])
				.map((frontier) => [
					frontier.id,
					frontier.row,
					frontier.col,
					frontier.status || "",
				].join(":"))
				.sort()
				.join("|");
		},
		pathSignature() {
			const paths = this.pathsByVehicle || {};
			return Object.keys(paths)
				.sort()
				.map((vehicleId) => {
					const steps = paths[vehicleId] || [];
					return `${vehicleId}:${steps.map((step) => `${step.row},${step.col}`).join(";")}`;
				})
				.join("|");
		},

		hoverObjectLoop() {
			if (!this.down) {
				this.intersectedNode = null;
				return;
			}
			this.raycaster.setFromCamera(this.mouse, this.camera);
			var intersects = this.raycaster.intersectObjects(this.clickableObjects);
			if (intersects.length > 0) {
				let coords;
				if (intersects[0].object.name == "wall") {
					coords = this.faceIndexToCoordinates(intersects[0].object.wallId * 2);
				} else {
					var faceIndex = intersects[0].faceIndex;
					coords = this.faceIndexToCoordinates(faceIndex);
				}

				if (this.grid[coords.row][coords.col] != this.intersectedNode) {
					let ends = ["start", "finish"];
					if (
						ends.includes(this.grid[coords.row][coords.col].status) ||
						(this.intersectedNode && ends.includes(this.intersectedNode.status))
					) {
						let end;
						if (ends.includes(this.grid[coords.row][coords.col].status)) {
							end = this.grid[coords.row][coords.col].status;
						} else {
							end = this.intersectedNode.status;
						}
						let obj = {};
						obj[end] = {
							row: coords.row,
							col: coords.col,
						};
						if (this.intersectedNode && ends.includes(this.intersectedNode.status)) {
							this.intersectedNode.status = "default";
						}
						this.grid[coords.row][coords.col].status = end;
						this.$emit("updateEnds", obj);
					} else if (this.selectedAlgorithm.type != 'unweighted' && (!this.intersectedNode || !ends.includes(this.intersectedNode.status))) {
						this.grid[coords.row][coords.col].status =
							this.grid[coords.row][coords.col].status == "wall" ? "default" : "wall";
					}

					this.intersectedNode = this.grid[coords.row][coords.col];
				}
			}
		},

		animatePlayer(delta) {
			let playerSpeed = 300;
			// Gradual slowdown
			this.pointerLock.velocity.x -= this.pointerLock.velocity.x * 10.0 * delta;
			this.pointerLock.velocity.z -= this.pointerLock.velocity.z * 10.0 * delta;

			if (this.detectPlayerCollision() == false) {
				this.pointerLock.direction.z =
					Number(this.pointerLock.moveForward) - Number(this.pointerLock.moveBackward);
				this.pointerLock.direction.x =
					Number(this.pointerLock.moveRight) - Number(this.pointerLock.moveLeft);
				this.pointerLock.direction.normalize(); // this ensures consistent movements in all directions
	
				if (this.pointerLock.moveForward || this.pointerLock.moveBackward)
					this.pointerLock.velocity.z -= this.pointerLock.direction.z * playerSpeed * delta;
				if (this.pointerLock.moveLeft || this.pointerLock.moveRight)
					this.pointerLock.velocity.x -= this.pointerLock.direction.x * playerSpeed * delta;
	
				this.controls.moveRight(-this.pointerLock.velocity.x * delta);
				this.controls.moveForward(-this.pointerLock.velocity.z * delta);
			} else {
				this.pointerLock.velocity.x = 0;
				this.pointerLock.velocity.z = 0;
			}

			this.pointerLock.velocity.y -= 9.8 * 50.0 * delta; // 50.0 = mass
			if(this.detectOnObject()) {
				this.pointerLock.velocity.y = Math.max(0, this.pointerLock.velocity.y);
				this.pointerLock.canJump = true;
			}
			this.controls.getObject().position.y += this.pointerLock.velocity.y * delta;

			if (this.controls.getObject().position.y < this.cameraY) {
				this.pointerLock.velocity.y = 0;
				this.controls.getObject().position.y = this.cameraY;
				this.pointerLock.canJump = true;
			}
		},

		detectPlayerCollision() {
			let rotationMatrix;
			// Get direction of camera
			let cameraDirection = this.controls.getDirection(new THREE.Vector3(0, 0, 0)).clone();
			let collisionDistance = 1;

			// Check which direction we're moving (not looking)
			// Flip matrix to that direction so that we can reposition the ray
			if (this.pointerLock.moveBackward) {
				rotationMatrix = new THREE.Matrix4();
				rotationMatrix.makeRotationY(this.degreesToRadians(180));
			} else if (this.pointerLock.moveLeft) {
				rotationMatrix = new THREE.Matrix4();
				rotationMatrix.makeRotationY(this.degreesToRadians(90));
			} else if (this.pointerLock.moveRight) {
				rotationMatrix = new THREE.Matrix4();
				rotationMatrix.makeRotationY(this.degreesToRadians(270));
			}

			// Player is not moving forward, apply rotation matrix needed
			if (rotationMatrix !== undefined) {
				cameraDirection.applyMatrix4(rotationMatrix);
			}

			// Apply ray to player camera
			let rayCaster = new THREE.Raycaster(this.controls.getObject().position, cameraDirection);

			// If our ray hit a collidable object, return true
			if (this.rayIntersect(rayCaster, collisionDistance)) {
				return true;
			} else {
				return false;
			}
		},

		detectOnObject() {
			let collisionDistance = this.cameraY+1;
			let rayCaster = new THREE.Raycaster(this.controls.getObject().position, new THREE.Vector3(0, -1, 0));
			// rayCaster.ray.origin.y -= this.cameraY;
			if (this.rayIntersect(rayCaster, collisionDistance)) {
				return true;
			} else {
				return false;
			}
		},

		deviceCamLoop() {
			let videoCtx = this.videoCanvas.getContext("2d");

			videoCtx.drawImage(this.video, 0, 0, this.videoCanvas.width, this.videoCanvas.height);
			let pixels = videoCtx.getImageData(0, 0, this.videoCanvas.width, this.videoCanvas.height);
			for(let y=0; y<this.videoCanvas.height; y++) {
				for(let x=0; x<this.videoCanvas.width; x++) {
					let index = (x + y * this.videoCanvas.width) * 4;
					let r = pixels.data[index+0];
					let g = pixels.data[index+1];
					let b = pixels.data[index+2];
					
					let brightness = Math.floor((r+g+b)/3);
					let gridX = Math.floor(this.videoCanvas.width-1-x);
					let status = "default";
					if (y == this.start.row && gridX == this.start.col) {
						status = "start";
					} else if (y == this.finish.row && gridX == this.finish.col) {
						status = "finish";
					}
					if(brightness > this.thresholdValue) {
						this.grid[y][gridX].status = status;
					} else if(status != 'start' && status != 'finish') {
						this.grid[y][gridX].status = 'wall';
					}
				}
			}
		},

		rayIntersect(ray, distance) {
			var intersects = ray.intersectObjects(this.collidableObjects);
			for (var i = 0; i < intersects.length; i++) {
				// Check if there's a collision
				if (intersects[i].distance < distance) {
					return true;
				}
			}
			return false;
		},

		addControls() {
			this.orbitControls = new OrbitControls(this.camera, this.renderer.domElement);
			this.pointerLockControls = new PointerLockControls(this.camera, this.renderer.domElement);
			this.pointerLockControls.addEventListener("lock", function() {
				console.log("Pointer Locked");
			});
			this.pointerLockControls.addEventListener("unlock", function() {
				console.log("Pointer Unlocked");
			});
			// Clock
			this.clock = new THREE.Clock();
			document.addEventListener("keydown", this.onKeyDown, false);
			document.addEventListener("keyup", this.onKeyUp, false);
			this.pointerLock.velocity = new THREE.Vector3();
			this.pointerLock.direction = new THREE.Vector3();
			this.scene.add(this.pointerLockControls.getObject());
		},

		setControls(fromInit = false) {
			let vm = this;
			TWEEN.removeAll();
			if (this.controlType == "Orbit") {
				// OrbitControls
				this.cameraY = this.defaultCameraY;
				this.camera.near = 1;
				this.camera.updateProjectionMatrix();
				this.controls = this.orbitControls;
				this.controls.enabled = true;
				setTimeout(() => {
					vm.resetCamera();
				}, fromInit ? 800 : 0);
			} else if (this.controlType == "PointerLock") {
				// PointerLock controls
				this.cameraY = 3;
				this.camera.near = 0.05;
				this.camera.updateProjectionMatrix();
				this.controls.enabled = false;
				this.controls = this.pointerLockControls;
				let startPosition = this.ground.geometry.vertices[
					this.grid[this.start.row][this.start.col].faces[1]["a"]
				];
				new TWEEN.Tween(this.camera.position)
					.to(startPosition, 2000)
					.easing(TWEEN.Easing.Exponential.Out)
					.start();
				new TWEEN.Tween(this.camera.rotation)
					.to({ x: 0, y: (5 * Math.PI) / 4, z: 0 }, 2000)
					.easing(TWEEN.Easing.Exponential.Out)
					.start();
			}
		},

		resetCamera() {
			new TWEEN.Tween(this.camera.position)
				.to({ x: 0, y: this.cameraY, z: 0 }, 2000)
				.easing(TWEEN.Easing.Exponential.Out)
				.onUpdate(() => {
					this.camera.lookAt(this.scene.position);
				})
				.onComplete(() => {
					let lookDirection = new THREE.Vector3();
					this.camera.getWorldDirection(lookDirection);
					this.controls.target
						.copy(this.camera.position)
						.add(lookDirection.multiplyScalar(this.cameraY));
				})
				.start();
			new TWEEN.Tween(this.camera.rotation)
				.to({ x: -Math.PI / 2, y: 0, z: 0 }, 2000)
				.easing(TWEEN.Easing.Exponential.Out)
				.start();
		},

		resizeHandler(event) {
			let width = window.innerWidth,
				height = window.innerHeight;
			this.renderer.setSize(width, height);
			this.camera.aspect = width / height;
			this.camera.updateProjectionMatrix();
		},

		initGrid() {
			this.clearNodeWatchers();
			if (this.grid.length > this.rows) {
				this.grid.splice(this.rows);
			}
			for (let i = 0; i < this.rows; i++) {
				let currentRow = this.grid[i] || [];
				for (let j = 0; j < this.cols; j++) {
					currentRow[j] = this.createNode(i, j, currentRow[j]);
				}
				if (currentRow.length > this.cols) {
					currentRow.splice(this.cols);
				}
				if (!this.grid[i]) {
					this.grid.push(currentRow);
				}
			}
			for (let i = 0; i < this.rows; i++) {
				for (let j = 0; j < this.cols; j++) {
					if (this.backendMode) continue;
					const unwatch = this.$watch(
						function() {
							return this.grid[i][j];
						},
						this.nodeWatcher,
						{ deep: true }
					);
					this.nodeWatchers.push(unwatch);
				}
			}
		},

		createNode(row, col, existingNode = null) {
			let faces = {};
			let faceIndex = row * 2 * this.cols + col * 2;
			faces[1] = this.ground.geometry.faces[faceIndex];
			faceIndex = faceIndex % 2 == 0 ? faceIndex + 1 : faceIndex - 1;
			faces[2] = this.ground.geometry.faces[faceIndex];

			let status = existingNode && existingNode.status ? existingNode.status : "default";
			if (!this.backendMode) {
				if (row == this.start.row && col == this.start.col) {
					status = "start";
				} else if (row == this.finish.row && col == this.finish.col) {
					status = "finish";
				}
			}

			// Node info
			let node = existingNode || {};
			node.id = row * this.cols + col;
			node.row = row;
			node.col = col;
			node.faces = faces;
			node.status = status;
			node.distance = Infinity;
			node.totalDistance = Infinity;
			node.heuristicDistance = null;
			node.direction = null;
			node.weight = 0;
			node.previousNode = null;

			if (status == "start") {
				tweenToColor(node, this.ground.geometry, [this.colors.start]);
			} else if (status == "finish") {
				tweenToColor(node, this.ground.geometry, [this.colors.finish]);
			}

			return node;
		},

		nodeWatcher(newVal, oldVal) {
			// console.log('WATCHER', newVal);
			if (this.visualizerState == "running" && !this.backendMode) return;
			this.updateNode(newVal, this.backendMode || this.streaming);
		},

		updateNode(node, instant = false) {
			if (!node || !node.faces || !this.ground) return;
			if (node.status == "wall") {
				let scaleY = this.backendMode ? 1 : 0.5 + Math.random();
				this.addWall(node, scaleY, instant ? 0 : 1000);
				this.colorNode(node, this.colors.wall, instant);
			} else if (node.status == "start") {
				this.colorNode(node, this.colors.start, instant);
			} else if (node.status == "finish") {
				this.colorNode(node, this.colors.finish, instant);
			} else if (node.status == "visited") {
				this.hideNodeWall(node);
				this.colorNode(node, this.colors.visited, instant);
			} else if (node.status == "unknown") {
				this.hideNodeWall(node);
				this.colorNode(node, this.colors.unknown || this.colors.default, instant);
			} else if (node.status == "reserved") {
				this.hideNodeWall(node);
				this.colorNode(node, this.colors.reserved || this.colors.path, instant);
			} else {
				this.hideNodeWall(node);
				this.colorNode(node, this.colors.default, instant);
			}
		},

		colorNode(node, color, instant = false) {
			if (!instant) {
				tweenToColor(node, this.ground.geometry, [color]);
				return;
			}
			node.faces[1].color.setRGB(color.r, color.g, color.b);
			node.faces[2].color.setRGB(color.r, color.g, color.b);
			this.ground.geometry.colorsNeedUpdate = true;
		},

		hideNodeWall(node) {
			if (this.walls[node.id] != null && this.walls[node.id].visible) {
				this.hideWall(this.walls[node.id]);
			}
		},

		addWall(node, scaleY, duration) {
			if (!!this.walls[node.id]) {
				if(!this.walls[node.id].visible) {
					this.showWall(this.walls[node.id], scaleY, duration);
				}
				return;
			}

			let materialId = this.wallMaterials.length > 1
				? 1 + Math.floor(Math.random() * (this.wallMaterials.length - 1))
				: 0;
			let wall = new THREE.Mesh(this.wallGeomtery, this.wallMaterials[materialId]);
			wall.name = "wall";
			wall.wallId = node.id;
			wall.scale.y = scaleY;
			wall.castShadow = false;
			wall.receiveShadow = false;
			this.scene.add(wall);
			this.$set(this.walls, node.id, wall);

			let gridWidth = this.cols * this.nodeDimensions.width;
			let gridHeight = this.rows * this.nodeDimensions.height;
			let height = this.wallGeomtery.parameters.height * wall.scale.y;
			let x = -gridWidth / 2 + this.nodeDimensions.width / 2 + node.col * this.nodeDimensions.width,
				y = height / 2,
				z =
					-gridHeight / 2 + this.nodeDimensions.height / 2 + node.row * this.nodeDimensions.height;
			
			if(duration == 0) {
				wall.position.set(x, y, z);
			} else {
				wall.position.set(x, height, z);
				new TWEEN.Tween(wall.position)
					.to({ x: x, y: y, z: z }, duration)
					.easing(TWEEN.Easing.Bounce.Out)
					.start();
			}
		},

		showWall(wall, scaleY, duration) {
			wall.scale.y = scaleY;
			let height = wall.geometry.parameters.height * wall.scale.y;
			wall.visible = true;
			if(duration == 0) {
				wall.position.setY(height/2);
			} else {
				wall.position.setY(height);
				new TWEEN.Tween(wall.position)
					.to({ y: height / 2 }, duration)
					.easing(TWEEN.Easing.Bounce.Out)
					.start();
			}
		},

		hideWall(wall) {
			wall.visible = false;
		},

		captureObstaclePaintEvent(event) {
			if (!event) return;
			if (event.preventDefault) event.preventDefault();
			if (event.stopPropagation) event.stopPropagation();
			if (event.stopImmediatePropagation) event.stopImmediatePropagation();
		},
		disableObstaclePaintControls() {
			if (!this.controls || this.controls.enabled === undefined || this.paintControlsEnabled !== null) return;
			this.paintControlsEnabled = this.controls.enabled;
			this.controls.enabled = false;
		},
		restoreObstaclePaintControls() {
			if (this.paintControlsEnabled !== null && this.controls && this.controls.enabled !== undefined) {
				this.controls.enabled = this.paintControlsEnabled;
			}
			this.paintControlsEnabled = null;
		},
		finishObstaclePaint(event) {
			this.captureObstaclePaintEvent(event);
			this.currentEvent = null;
			this.moved = false;
			this.down = false;
			this.intersectedNode = null;
			this.paintingObstacle = false;
			this.restoreObstaclePaintControls();
			if (this.$listeners.paintEnd) {
				this.$emit("paintEnd");
			}
		},
		onMouseDown(event) {
			if (this.obstaclePaintingEnabled) {
				this.captureObstaclePaintEvent(event);
				this.paintingObstacle = true;
				this.disableObstaclePaintControls();
				this.down = true;
				this.moved = false;
				this.currentEvent = event;
				this.setMouseVector(event, "move");
				this.intersectedNode = null;
				this.paintHoveredNode();
				this.clearFocus();
				return;
			}
			this.down = true;
			this.moved = false;
			this.currentEvent = event;
			this.setMouseVector(event, "move");
			this.clearFocus();
		},
		onMouseMove(event) {
			if (!this.down) return;
			this.moved = true;
			if (this.paintingObstacle) {
				this.captureObstaclePaintEvent(event);
				this.setMouseVector(event, "move");
				this.paintHoveredNode();
				return;
			}
			if (this.worldSetup) {
				this.setMouseVector(event, "move");
			}
		},
		onMouseLeave(event) {
			if (this.paintingObstacle) {
				this.finishObstaclePaint(event);
				return;
			}
			if (this.moved) {
				this.onMouseup(event);
			}
			this.down = false;
		},
		onMouseup(event) {
			if (this.paintingObstacle) {
				this.finishObstaclePaint(event);
				return;
			}
			let threshold = 25;
			if (this.moved) {
				let dist = 0;
				if (this.currentEvent.touches && this.currentEvent.touches.length > 0) {
					dist = this.calcDist(
						this.currentEvent.touches[0].pageX - event.changedTouches[0].pageX,
						this.currentEvent.touches[0].pageY - event.changedTouches[0].pageY
					);
					dist > threshold ? this.moveHandler(event) : this.clickHandler(event);
				} else {
					this.moveHandler(event);
				}
			} else {
				this.clickHandler(event);
			}
			this.currentEvent = null;
			this.moved = false;
			this.down = false;
			this.intersectedNode = null;
		},

		calcDist(x, y) {
			return x * x + y * y;
		},

		setMouseVector(event, type) {
			let touchEvent = type == "click" ? this.currentEvent : event;
			if (touchEvent.touches && touchEvent.touches.length > 0) {
				this.mouse.x = (touchEvent.touches[0].clientX / window.innerWidth) * 2 - 1;
				this.mouse.y = -(touchEvent.touches[0].clientY / window.innerHeight) * 2 + 1;
			} else {
				this.mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
				this.mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;
			}
		},

		moveHandler(event) {
			// console.log("Moved");
		},
		paintHoveredNode() {
			if (this.worldSetup || this.controlType == "PointerLock") return;
			this.raycaster.setFromCamera(this.mouse, this.camera);
			let intersects = this.raycaster.intersectObjects(this.clickableObjects);
			if (intersects.length <= 0) return;
			let coords;
			if (intersects[0].object.name == "wall") {
				coords = this.faceIndexToCoordinates(intersects[0].object.wallId * 2);
			} else {
				coords = this.faceIndexToCoordinates(intersects[0].faceIndex);
			}
			if (!this.grid[coords.row] || !this.grid[coords.row][coords.col]) return;
			if (this.grid[coords.row][coords.col] === this.intersectedNode) return;
			this.intersectedNode = this.grid[coords.row][coords.col];
			this.$emit("paintEvent", this.intersectedNode);
		},

		clickHandler(event) {
			if (this.worldSetup || this.controlType == "PointerLock") return;
			this.setMouseVector(event, "click");
			this.raycaster.setFromCamera(this.mouse, this.camera);
			let intersects = this.raycaster.intersectObjects(this.clickableObjects); //array
			if (intersects.length > 0) {
				let coords;
				if (intersects[0].object.name == "wall") {
					coords = this.faceIndexToCoordinates(intersects[0].object.wallId * 2);
				} else {
					var faceIndex = intersects[0].faceIndex;
					coords = this.faceIndexToCoordinates(faceIndex);
				}
				this.$emit("clickEvent", this.grid[coords.row][coords.col]);
			}
		},

		degreesToRadians(degrees) {
			return degrees * Math.PI/180;
		},

		faceIndexToCoordinates(faceIndex) {
			// As each node has 2 faces
			return {
				row: Math.floor(faceIndex / 2 / this.cols),
				col: Math.floor((faceIndex / 2) % this.cols),
			};
		},

		clearFocus() {
			document.getElementsByClassName("header")[0].click();
		},

		onKeyDown(event) {
			if (this.controlType == "Orbit") {
				switch (event.keyCode) {
					// case 72:  // h
					// 	this.hemisphereLight.visible = !this.hemisphereLight.visible;
					// 	break;
					// case 68: // d
					// 	this.directionalLight.visible = !this.directionalLight.visible;
					// 	break;
					case 87: // w
						this.$emit('switchWorldSetup');
						break;
					case 80: // p
						this.$emit('switchControlType');
						break;
				}
			} else {
				switch (event.keyCode) {
					case 38: // up
					case 87: // w
						this.pointerLock.moveForward = true;
						break;
					case 37: // left
					case 65: // a
						this.pointerLock.moveLeft = true;
						break;
					case 40: // down
					case 83: // s
						this.pointerLock.moveBackward = true;
						break;
					case 39: // right
					case 68: // d
						this.pointerLock.moveRight = true;
						break;
					case 32: // space
						if (this.pointerLock.canJump === true) this.pointerLock.velocity.y += 200;
						this.pointerLock.canJump = false;
						break;
					case 80: // P
						if(!this.controls.isLocked) {
							this.$emit('switchControlType');
						}
						break;
				}
			}
		},

		onKeyUp(event) {
			switch (event.keyCode) {
				case 38: // up
				case 87: // w
					this.pointerLock.moveForward = false;
					break;
				case 37: // left
				case 65: // a
					this.pointerLock.moveLeft = false;
					break;
				case 40: // down
				case 83: // s
					this.pointerLock.moveBackward = false;
					break;
				case 39: // right
				case 68: // d
					this.pointerLock.moveRight = false;
					break;
			}
		},
	},
};
</script>

<style lang="scss">
#visualizer {
	height: 100vh;
	width: 100vw;
}
</style>
