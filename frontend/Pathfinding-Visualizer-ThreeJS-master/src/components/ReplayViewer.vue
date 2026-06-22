<template>
  <main class="replay-page">
    <header>
      <div>
        <p>历史运行记录</p>
        <h1>仿真回放</h1>
      </div>
      <button type="button" title="刷新回放列表" @click="loadReplays">刷新</button>
    </header>

    <div class="replay-layout">
      <aside class="replay-list">
        <div class="list-title">
          <h2>回放记录</h2>
          <span>{{ replays.length }} 条</span>
        </div>
        <p v-if="error" class="error">{{ error }}</p>
        <button
          v-for="item in replays"
          :key="item.replayId"
          type="button"
          :class="['replay-item', { active: selectedId === item.replayId }]"
          @click="selectReplay(item.replayId)"
        >
          <strong>{{ formatDate(item.startedAt) }}</strong>
          <span>{{ item.operator || '未知运行员' }} · {{ item.vehicleCount || 0 }} 辆车</span>
          <span>覆盖率 {{ percent(item.lastCoverage) }} · {{ item.frameCount || 0 }} 帧</span>
        </button>
        <p v-if="!loading && !replays.length" class="empty">尚无回放记录</p>
      </aside>

      <section v-if="selected" class="viewer">
        <div class="viewer-toolbar">
          <div>
            <h2>{{ formatDate(selected.startedAt) }}</h2>
            <span>{{ selected.operator }} · {{ selected.policy || '-' }} · {{ selected.navigatorAlgorithm || '-' }}</span>
          </div>
          <div class="playback-actions">
            <button type="button" :title="playing ? '暂停' : '播放'" @click="togglePlay">
              {{ playing ? '暂停' : '播放' }}
            </button>
            <select v-model.number="speed" title="播放速度">
              <option :value="1">1 倍速</option>
              <option :value="2">2 倍速</option>
              <option :value="4">4 倍速</option>
            </select>
            <button class="delete-button" type="button" title="删除当前回放" @click="removeReplay">
              删除
            </button>
          </div>
        </div>

        <div class="visual-band">
          <canvas ref="mapCanvas" class="map-canvas" width="900" height="540" />
          <div class="metrics">
            <div>
              <span>当前帧</span>
              <strong>{{ currentIndex + 1 }} / {{ frames.length }}</strong>
            </div>
            <div>
              <span>覆盖率</span>
              <strong>{{ percent(currentCoverage) }}</strong>
            </div>
            <div>
              <span>运行步数</span>
              <strong>{{ frameValue('runtime.movementSteps', 0) }}</strong>
            </div>
            <div>
              <span>车辆数量</span>
              <strong>{{ currentVehicles.length }}</strong>
            </div>
          </div>
        </div>

        <div class="timeline">
          <input
            v-model.number="currentIndex"
            type="range"
            min="0"
            :max="Math.max(0, frames.length - 1)"
            step="1"
            @input="drawFrame"
          >
          <div>
            <span>{{ frameTime }}</span>
            <span>{{ replayDuration }}</span>
          </div>
        </div>

        <div class="data-grid">
          <section>
            <h3>车辆数据</h3>
            <div class="data-table">
              <table>
                <thead>
                  <tr><th>车辆</th><th>位置</th><th>状态</th><th>目标</th></tr>
                </thead>
                <tbody>
                  <tr v-for="vehicle in currentVehicles" :key="vehicle.id">
                    <td>{{ vehicle.vehicleId || vehicle.id }}</td>
                    <td>{{ pointText((vehicle.pose && vehicle.pose.position) || vehicle.position) }}</td>
                    <td>{{ vehicle.status || '-' }}</td>
                    <td>{{ pointText(vehicle.target) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h3>本帧黑板数据</h3>
            <dl>
              <div><dt>前沿点</dt><dd>{{ dataCount('frontiers') }}</dd></div>
              <div><dt>探索任务</dt><dd>{{ dataCount('tasks') }}</dd></div>
              <div><dt>导航请求</dt><dd>{{ dataCount('navigationRequests') }}</dd></div>
              <div><dt>导航方案</dt><dd>{{ dataCount('navigationPlans') }}</dd></div>
              <div><dt>系统事件</dt><dd>{{ dataCount('events') }}</dd></div>
              <div><dt>运行状态</dt><dd>{{ frameValue('systemStatus', '-') }}</dd></div>
            </dl>
          </section>
        </div>
      </section>

      <section v-else class="no-selection">
        <h2>选择一条记录开始回放</h2>
        <p>每一帧均包含当时的地图、车辆、任务、导航和系统运行数据。</p>
      </section>
    </div>
  </main>
</template>

<script>
import api from '../services/api'

export default {
  name: 'ReplayViewer',
  props: {
    currentUser: {
      type: Object,
      required: true,
    },
  },
  data() {
    return {
      replays: [],
      selected: null,
      selectedId: '',
      frames: [],
      currentIndex: 0,
      playing: false,
      speed: 1,
      timer: null,
      loading: false,
      error: '',
    }
  },
  computed: {
    currentFrame() {
      return this.frames[this.currentIndex] || {}
    },
    currentSnapshot() {
      return this.currentFrame.snapshot || {}
    },
    currentVehicles() {
      const vehicles = this.currentSnapshot.vehicles || []
      return Array.isArray(vehicles) ? vehicles : Object.values(vehicles)
    },
    currentCoverage() {
      const map = this.currentSnapshot.map || {}
      const states = map.cellStates || ''
      if (states.length) {
        const known = states.length - (states.match(/U/g) || []).length
        return known / states.length * 100
      }
      const cells = map.cells || []
      if (!cells.length) return 0
      return cells.filter((cell) => cell.state !== 'UNKNOWN').length / cells.length * 100
    },
    frameTime() {
      if (!this.currentFrame.timestamp) return '00:00'
      const start = Number(this.selected.startedAt)
      const current = Number(this.currentFrame.timestamp)
      return this.formatDuration(Math.max(0, current - start))
    },
    replayDuration() {
      if (!this.frames.length) return '00:00'
      const start = Number(this.selected.startedAt)
      const end = Number(this.frames[this.frames.length - 1].timestamp)
      return this.formatDuration(Math.max(0, end - start))
    },
  },
  watch: {
    currentIndex() {
      this.$nextTick(this.drawFrame)
    },
    speed() {
      if (this.playing) {
        this.stopTimer()
        this.startTimer()
      }
    },
  },
  mounted() {
    this.loadReplays()
    window.addEventListener('resize', this.drawFrame)
  },
  beforeDestroy() {
    this.stopTimer()
    window.removeEventListener('resize', this.drawFrame)
  },
  methods: {
    async loadReplays() {
      this.loading = true
      this.error = ''
      try {
        this.replays = await api.listReplays()
        if (!this.selectedId && this.replays.length) {
          await this.selectReplay(this.replays[0].replayId)
        } else if (this.selectedId && !this.replays.some((item) => item.replayId === this.selectedId)) {
          this.clearSelection()
        }
      } catch (error) {
        this.error = error.message
      } finally {
        this.loading = false
      }
    },
    async selectReplay(id) {
      this.stopTimer()
      this.playing = false
      this.selectedId = id
      this.error = ''
      try {
        const detail = await api.getReplay(id)
        this.selected = detail.meta || detail
        this.frames = detail.frames || []
        this.currentIndex = 0
        this.$nextTick(this.drawFrame)
      } catch (error) {
        this.error = error.message
      }
    },
    async removeReplay() {
      if (!this.selectedId || !window.confirm('确定删除这条回放及其全部数据吗？')) return
      this.stopTimer()
      this.playing = false
      this.error = ''
      try {
        await api.deleteReplay(this.selectedId)
        this.clearSelection()
        await this.loadReplays()
      } catch (error) {
        this.error = error.message
      }
    },
    clearSelection() {
      this.selectedId = ''
      this.selected = null
      this.frames = []
      this.currentIndex = 0
    },
    togglePlay() {
      if (!this.frames.length) return
      if (this.playing) {
        this.stopTimer()
        this.playing = false
        return
      }
      if (this.currentIndex >= this.frames.length - 1) this.currentIndex = 0
      this.playing = true
      this.startTimer()
    },
    startTimer() {
      this.timer = window.setInterval(() => {
        if (this.currentIndex >= this.frames.length - 1) {
          this.stopTimer()
          this.playing = false
          return
        }
        this.currentIndex += 1
      }, Math.max(100, 700 / this.speed))
    },
    stopTimer() {
      if (this.timer) window.clearInterval(this.timer)
      this.timer = null
    },
    frameValue(path, fallback = null) {
      const source = this.currentSnapshot
      const value = path.split('.').reduce((result, key) => (
        result !== null && result !== undefined ? result[key] : undefined
      ), source)
      return value === undefined || value === null ? fallback : value
    },
    drawFrame() {
      const canvas = this.$refs.mapCanvas
      if (!canvas) return
      const context = canvas.getContext('2d')
      const map = this.currentSnapshot.map || {}
      const grid = map.cells || []
      const cellStates = map.cellStates || ''
      const rows = map.height || 1
      const cols = map.width || 1
      const width = canvas.width
      const height = canvas.height
      const cell = Math.min(width / cols, height / rows)
      const offsetX = (width - cols * cell) / 2
      const offsetY = (height - rows * cell) / 2

      context.fillStyle = '#20282b'
      context.fillRect(0, 0, width, height)

      if (cellStates) {
        for (let index = 0; index < cellStates.length; index += 1) {
          context.fillStyle = this.cellColor(cellStates[index])
          context.fillRect(
            offsetX + (index % cols) * cell,
            offsetY + Math.floor(index / cols) * cell,
            Math.ceil(cell),
            Math.ceil(cell),
          )
        }
      } else {
        grid.forEach((mapCell) => {
          context.fillStyle = this.cellColor(mapCell.state)
          context.fillRect(
            offsetX + Number(mapCell.x) * cell,
            offsetY + Number(mapCell.y) * cell,
            Math.ceil(cell),
            Math.ceil(cell),
          )
        })
      }

      const colors = ['#ef5b5b', '#35b8e0', '#f2c14e', '#8bc34a', '#d17bdf', '#ff8c42']
      this.currentVehicles.forEach((vehicle, index) => {
        const point = (vehicle.pose && vehicle.pose.position) || vehicle.position
        if (!point) return
        const x = Array.isArray(point) ? point[0] : point.x
        const y = Array.isArray(point) ? point[1] : point.y
        if (!Number.isFinite(Number(x)) || !Number.isFinite(Number(y))) return
        context.beginPath()
        context.fillStyle = colors[index % colors.length]
        context.arc(
          offsetX + (Number(x) + 0.5) * cell,
          offsetY + (Number(y) + 0.5) * cell,
          Math.max(4, Math.min(10, cell * 0.42)),
          0,
          Math.PI * 2,
        )
        context.fill()
        context.lineWidth = 2
        context.strokeStyle = '#ffffff'
        context.stroke()
      })
    },
    cellColor(value) {
      if (value === 'OBSTACLE' || value === 'O') return '#111719'
      if (value === 'FREE' || value === 'F') return '#d7e0dc'
      if (value === 'VISITED' || value === 'V') return '#86aa9d'
      return '#596568'
    },
    collectionSize(value) {
      if (Array.isArray(value)) return value.length
      if (value && typeof value === 'object') return Object.keys(value).length
      return 0
    },
    dataCount(name) {
      const counts = this.currentSnapshot.dataCounts || {}
      if (counts[name] !== undefined) return counts[name]
      return this.collectionSize(this.currentSnapshot[name] || [])
    },
    pointText(point) {
      if (!point) return '-'
      if (Array.isArray(point)) return `(${point[0]}, ${point[1]})`
      if (point.x !== undefined) return `(${point.x}, ${point.y})`
      return '-'
    },
    percent(value) {
      const number = Number(value || 0)
      return `${number.toFixed(1)}%`
    },
    formatDate(value) {
      return value ? new Date(value).toLocaleString('zh-CN') : '-'
    },
    formatDuration(milliseconds) {
      const seconds = Math.floor(milliseconds / 1000)
      const minutes = Math.floor(seconds / 60)
      return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
    },
  },
}
</script>

<style scoped>
.replay-page {
  min-height: 100%;
  padding: 30px 34px 76px;
  background: #edf1f0;
}

header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  margin-bottom: 22px;
}

header p {
  margin: 0 0 3px;
  color: #187561;
  font-size: 13px;
  font-weight: 700;
}

h1 {
  margin: 0;
  font-size: 30px;
}

button,
select {
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid #b9c4c1;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
}

.replay-layout {
  display: grid;
  min-height: calc(100vh - 145px);
  grid-template-columns: 280px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #d4dcda;
  border-radius: 8px;
  background: #fff;
}

.replay-list {
  padding: 18px 12px;
  overflow-y: auto;
  border-right: 1px solid #dce2e0;
  background: #f7f9f8;
}

.list-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 0 8px 12px;
}

h2,
h3 {
  margin: 0;
}

.list-title h2 {
  font-size: 17px;
}

.list-title span {
  color: #7b8583;
  font-size: 12px;
}

.replay-item {
  display: flex;
  width: 100%;
  height: auto;
  align-items: start;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 7px;
  padding: 12px;
  border-color: transparent;
  text-align: left;
}

.replay-item strong {
  font-size: 13px;
}

.replay-item span {
  color: #707b79;
  font-size: 12px;
}

.replay-item.active {
  border-color: #7fb4a7;
  background: #e7f3ef;
}

.viewer {
  min-width: 0;
  padding: 20px;
  overflow-y: auto;
}

.viewer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.viewer-toolbar h2 {
  font-size: 18px;
}

.viewer-toolbar span {
  display: block;
  margin-top: 4px;
  color: #75807e;
  font-size: 12px;
}

.playback-actions {
  display: flex;
  gap: 7px;
}

.delete-button {
  border-color: #c89c9c;
  color: #a62f2f;
}

.visual-band {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 170px;
  overflow: hidden;
  border-radius: 6px;
  background: #20282b;
}

.map-canvas {
  display: block;
  width: 100%;
  aspect-ratio: 5 / 3;
  object-fit: contain;
}

.metrics {
  display: grid;
  align-content: center;
  gap: 1px;
  background: #303a3d;
}

.metrics div {
  display: flex;
  min-height: 76px;
  justify-content: center;
  flex-direction: column;
  padding: 12px 18px;
  color: #d5dfdd;
  background: #273033;
}

.metrics span {
  margin-bottom: 5px;
  font-size: 12px;
}

.metrics strong {
  color: #fff;
  font-size: 20px;
}

.timeline {
  padding: 14px 2px 20px;
}

.timeline input {
  width: 100%;
  accent-color: #187561;
}

.timeline div {
  display: flex;
  justify-content: space-between;
  color: #697572;
  font-size: 12px;
}

.data-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(260px, 0.5fr);
  gap: 22px;
}

.data-grid h3 {
  margin-bottom: 10px;
  font-size: 15px;
}

.data-table {
  overflow-x: auto;
  border-top: 1px solid #dfe5e3;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  height: 38px;
  padding: 0 8px;
  border-bottom: 1px solid #e2e7e6;
  text-align: left;
  font-size: 12px;
}

th {
  color: #66716f;
  background: #f7f9f8;
}

dl {
  display: grid;
  grid-template-columns: 1fr 1fr;
  margin: 0;
  border-top: 1px solid #dfe5e3;
}

dl div {
  padding: 10px;
  border-bottom: 1px solid #e2e7e6;
}

dt {
  color: #77817f;
  font-size: 11px;
}

dd {
  margin: 4px 0 0;
  font-size: 14px;
  font-weight: 700;
}

.no-selection {
  display: grid;
  align-content: center;
  justify-items: center;
  color: #71807c;
}

.no-selection h2 {
  color: #33413d;
}

.empty,
.error {
  padding: 10px;
  color: #7a8582;
  font-size: 13px;
}

.error {
  color: #a23636;
}

@media (max-width: 850px) {
  .replay-page {
    padding: 20px 14px 74px;
  }

  .replay-layout {
    grid-template-columns: 1fr;
  }

  .replay-list {
    max-height: 220px;
    border-right: 0;
    border-bottom: 1px solid #dce2e0;
  }

  .visual-band,
  .data-grid {
    grid-template-columns: 1fr;
  }

  .metrics {
    grid-template-columns: repeat(2, 1fr);
  }

  .metrics div {
    min-height: 64px;
  }
}
</style>
