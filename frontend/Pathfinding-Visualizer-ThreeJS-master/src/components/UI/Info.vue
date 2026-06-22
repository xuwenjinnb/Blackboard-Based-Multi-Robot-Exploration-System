<template>
	<div class="info-container" ref="infoBox" :class="containerClasses">
		<button class="btn-close" @click="resetToLegends" v-if="status != ''">&#10006;</button>
		<h2>{{ current.heading }}</h2>
		<p class="main-content" v-html="current.text"></p>
		<div class="swarm-unlocked" v-if="status == 'attributions' && swarmUnlocked">群体算法已解锁</div>
		<div class="info-buttons">
			<Button class="danger" @click="showAttributions" v-if="status == ''">说明</Button>
			<a href="https://github.com/dhruvmisra/Pathfinding-Visualizer-ThreeJS" target="_blank">
				<Button class="white" v-if="status == ''">
					<img src="@/assets/icons/github-logo.svg" alt="" />
				</Button>
			</a>
		</div>
		<img class="info-icon" src="@/assets/icons/info.svg">
	</div>
</template>

<script>
export default {
	props: {
		info: Object,
		colors: Object
	},
	data: () => ({
		status: '',
		current: {
			heading: "",
			text: ""
		},
		clemCounter: 0,
		clemTimeout: null,
		swarmUnlocked: false,
		legends: {
			heading: "寻路可视化",
			text: ""
		},
		attributions: {
			heading: "项目说明",
			text: `<div style="text-align: left">
				<h3 style="margin: 5px 0; opacity: 0.4">项目来源</h3>
				本界面基于 Pathfinding Visualizer ThreeJS 项目改造，用于三维展示网格寻路算法。<br>
				灵感来自 <span id="clem">Clément Mihailescu</span> 的寻路可视化项目。
				<br><br>
				<h3 style="margin: 5px 0; opacity: 0.4">WebGL 库</h3>
				Three.js
				<br><br>
				<h3 style="margin: 5px 0; opacity: 0.4">资源与图标</h3>
				贴图来自 <a href="https://opengameart.org/" target="_blank">OpenGameArt.org</a><br>
				图标来自 <a href="https://www.flaticon.com/authors/freepik" target="_blank">Freepik</a> / <a href="https://www.flaticon.com/" target="_blank">Flaticon</a>
				<br><br>
				<h3 style="margin: 5px 0; opacity: 0.4">源代码</h3>
				原项目仓库：<a href="https://github.com/dhruvmisra/Pathfinding-Visualizer-ThreeJS" target="_blank">Pathfinding-Visualizer-ThreeJS</a>.
				<br><br>
				<p style="text-align: center; margin: 1em 0;">使用 Vue.js 和 Three.js 构建</p>
			</div>`
		}
	}),
	computed: {
		containerClasses() {
			let classes = {
				centered: this.status == 'attributions'
			}
			classes[this.status] = true;
			return classes;
		}
	},
	created() {
		this.current = this.legends;
	},
	mounted() {
		this.constructLegends();
	},
	methods: {
		constructLegends() {
			this.legends.text += `<table class="legends-table">
				<tr>
					<td>
						<div class="square" style="background-color: ${this.getRGBString(this.colors.start)}"></div>
					</td>
					<td>起点</td>
				</tr>
				<tr>
					<td>
						<div class="square" style="background-color: ${this.getRGBString(this.colors.finish)}"></div>
					</td>
					<td>终点</td>
				</tr>
				<tr>
					<td>
						<div class="square" style="background-color: ${this.getRGBString(this.colors.visited)}"></div>
					</td>
					<td>已访问节点</td>
				</tr>
				<tr>
					<td>
						<div class="square" style="background-color: ${this.getRGBString(this.colors.path)}"></div>
					</td>
					<td>路径节点</td>
				</tr>
			</table>`
		},

		getRGBString(color) {
			return `rgb(${color.r*255}, ${color.g*255}, ${color.b*255})`;
		},

		showAttributions() {
			this.current = this.attributions;
			this.status = 'attributions';
			if(this.swarmUnlocked) return;
			this.$nextTick(() => {
				document.getElementById('clem').addEventListener('click', this.clemClick);
			});
		},

		clemClick() {
			if(this.swarmUnlocked) return;

			clearTimeout(this.clemTimeout);
			this.clemCounter++;
			if(this.clemCounter == 5) {
				this.$emit('unlockSwarm');
				this.swarmUnlocked = true;
			}
			this.clemTimeout = setTimeout(() => {
				this.clemCounter = 0;
			}, 3000);
		},

		resetToLegends() {
			this.$refs.infoBox.classList.remove('error');
			let clem = document.getElementById('clem');
			if(clem) {
				clem.removeEventListener('click', this.clemClick);
			}
			this.current = this.legends;
			this.status = '';
		},

		alert(info) {
			this.$refs.infoBox.classList.remove('error');
			this.$refs.infoBox.classList.add('alert');
			if(info) {
				this.current = info;
			}
			setTimeout(() => {
				this.$refs.infoBox.classList.remove('alert');
			}, 1000);
		},

		error(info) {
			this.$refs.infoBox.classList.remove('error');
			setTimeout(() => {
				this.$refs.infoBox.classList.add('error');
			}, 0)
			if(info) {
				this.current = info;
			}
		}
	}
}
</script>

<style lang="scss">
@import '@/scss/variables.scss';

.info-container {
	position: absolute;
	right: 15px;
	bottom: 15px;
	width: 350px;
	max-height: 100%;
	max-width: 90%;
	display: flex;
	flex-direction: column;
	font-size: 0.9em;
	padding: 25px;
	border-radius: 5px;
	background: linear-gradient(0, $dark 0%, #000000 240%);
	color: white;
	box-shadow: 2px 10px 30px rgba(#000, 0.4);
	opacity: 0.4;
	z-index: 10000;
	clip-path: circle(30px at calc(100% - 30px) calc(100% - 30px));
	transition: all 400ms ease-in-out;

	&:hover {
		clip-path: circle(200% at calc(100% - 30px) calc(100% - 30px));
		opacity: 1;
		bottom: 20px;
	}

	&.centered {
		max-height: 90%;
		min-height: 50%;
		width: 600px;
		max-width: 95%;
		opacity: 1;
		font-size: 1em;
		text-align: center;
		right: 50%;
		bottom: 50%;
		transform: translate(50%, 50%);
		clip-path: circle(200% at calc(100% - 30px) calc(100% - 30px));
	}

	&.alert {
		animation: alert 1000ms ease-in-out;
	}
	@keyframes alert {
		0%, 100% {
			bottom: 15px;
			opacity: 0.4;
		}
		20%, 50% {
			bottom: 30px;
			opacity: 1;
		}
		40% {
			bottom: 25px;
			opacity: 1;
		}
	}

	&.error {
		background: linear-gradient(0, brown 0%, #000000 240%);
		animation: error 400ms ease-out;
	}
	@keyframes error {
		0%, 100% {
			right: 15px;
			opacity: 0.4;
		}
		20%, 60% {
			right: 25px;
			opacity: 1;
		}
		40%, 80% {
			right: 5px;
			opacity: 1;
		}
	}

	.main-content {
		opacity: 0.9;
		margin-bottom: 3em;
		overflow: auto;
	}
	&.attributions {
		.main-content {
			margin-bottom: 0;
		}
		#clem {
			cursor: pointer;
			user-select: none;
			-moz-user-select: none;
			-webkit-user-select: none;
		}
		.swarm-unlocked {
			width: fit-content;
			margin: 0 auto;
			padding: 5px;
			font-size: 0.8em;
			border-radius: 5px;
			color: #0f0;
			background: rgba(#0f0, 0.3);
		}
	}

	h2 {
		margin: 0.5em 0;
	}

	.btn-close {
		position: absolute;
		top: 10px;
		right: 10px;
		height: 30px;
		width: 30px;
		border: none;
		border-radius: 50%;
		background: transparent;
		color: white;
		cursor: pointer;
		transition: background 200ms ease-out;
		&:hover {
			background: rgba(255, 255, 255, 0.1);
		}
		&:focus {
			outline: none;
		}
	}

	a {
		color: rgb(255, 124, 124);
	}

	img {
		border-radius: 5px;
	}

	table {
		border-spacing: 0;
		font-size: 0.9em;

		&.camera-table {
			margin: 0 auto;

			td {
				width: 50%;
				border: solid 1px white;
				padding: 10px;
			}
		}
		&.legends-table {
			td {
				padding: 5px;

				.square {
					width: 30px;
					height: 30px;
					margin: 0 auto;
				}
			}
		}
	}

	.info-buttons {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		margin-top: auto;

		.tutorial-buttons {
			display: flex;
			flex-wrap: wrap;
			align-items: center;
			width: 95%;
		}

		.btn-group {
			display: flex;
			margin: 0 auto;
		}
		.btn-tutorial {
			padding: 0 1em;
		}
	}

	.info-icon {
		position: absolute;
		right: 10px;
		bottom: 10px;
		height: 40px;
	}
}
</style>
