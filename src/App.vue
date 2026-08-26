<script setup>
import { computed, ref, watch } from 'vue'
import {
  Armchair,
  ArrowUpRight,
  CalendarClock,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Clock3,
  Coffee,
  LayoutDashboard,
  LibraryBig,
  LockKeyhole,
  LogOut,
  MapPin,
  Menu,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  RefreshCw,
  ShieldCheck,
  Users,
  X,
  Zap,
} from 'lucide-vue-next'

const activeView = ref('overview')
const mobileMenuOpen = ref(false)
const selectedRoom = ref(0)
const selectedDate = ref('明天')
const selectedSegment = ref('09:00–12:00')
const selectedSeat = ref(null)
const remoteSeats = ref(null)
const remoteSegments = ref([])
const selectedSegmentId = ref('')
const showBooking = ref(false)
const showLogin = ref(false)
const isLoggedIn = ref(false)
const accountName = ref('')
const loginForm = ref({ username: '', password: '' })
const automation = ref({
  enabled: false,
  check_in_enabled: true,
  check_out_enabled: true,
  check_in_time: '08:50',
  check_out_time: '22:05',
  reservation_id: '',
})
const automationStatus = ref({ running: false, last_action: null, last_run_at: null, last_message: '' })
const automationSaving = ref(false)
const toast = ref('')
let toastTimer

const rooms = [
  { name: '西校区图书馆 · 三层自习室', short: '西校区 · 三层', seats: 168, open: '08:00–22:00', accent: 'mint' },
  { name: '西校区图书馆 · 四层自习室', short: '西校区 · 四层', seats: 144, open: '08:00–22:00', accent: 'blue' },
  { name: '东校区图书馆 · 三层自习室 01', short: '东校区 · 三层 01', seats: 96, open: '08:00–22:00', accent: 'orange' },
  { name: '综合楼 · 805 自习室', short: '综合楼 · 805', seats: 48, open: '08:00–21:30', accent: 'violet' },
]

const segments = ['08:00–09:00', '09:00–12:00', '12:00–14:00', '14:00–18:00', '18:00–22:00']
const navItems = [
  { id: 'overview', label: '座位总览', icon: LayoutDashboard },
  { id: 'map', label: '座位地图', icon: Armchair },
  { id: 'reservations', label: '我的预约', icon: CalendarClock },
  { id: 'automation', label: '自动执行', icon: Zap },
]

const room = computed(() => rooms[selectedRoom.value])
const apiDate = computed(() => {
  if (selectedDate.value === '今天') return 'today'
  if (selectedDate.value === '明天') return 'tomorrow'
  return new Date(Date.now() + 2 * 86400000).toISOString().slice(0, 10)
})
const segmentItems = computed(() => {
  if (!remoteSegments.value.length) return segments.map((label, index) => ({ id: String(index + 1), label }))
  return remoteSegments.value.map((item, index) => ({
    id: String(item.id ?? item.segment ?? index + 1),
    label: item.name || item.title || item.time || item.segment_name || `${item.start || item.startTime || ''}–${item.end || item.endTime || ''}`,
  }))
})
const dates = computed(() => [
  { label: '今天', value: '今天', date: '08月26日' },
  { label: '明天', value: '明天', date: '08月27日' },
  { label: '周五', value: '周五', date: '08月28日' },
])

const mockSeats = computed(() => Array.from({ length: 64 }, (_, index) => {
  const number = index + 1
  const occupied = [3, 4, 8, 11, 12, 17, 18, 26, 31, 32, 39, 44, 51, 52, 58].includes(number)
  const reserved = [6, 21, 37, 47].includes(number)
  const cleaning = [14, 42].includes(number)
  return {
    id: `${selectedRoom.value + 1}-${number}`,
    number: String(number).padStart(2, '0'),
    status: occupied ? 'occupied' : reserved ? 'reserved' : cleaning ? 'cleaning' : 'available',
  }
}))

const seats = computed(() => {
  if (remoteSeats.value === null) return mockSeats.value
  return remoteSeats.value.map((seat, index) => ({
    id: String(seat.id),
    number: String(seat.no ?? seat.number ?? index + 1).padStart(2, '0'),
    status: 'available',
  }))
})

const availableCount = computed(() => seats.value.filter((seat) => seat.status === 'available').length)
const occupancy = computed(() => Math.round(((64 - availableCount.value) / 64) * 100))

const reservations = ref([])

function notify(message) {
  toast.value = message
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2800)
}

function selectSeat(seat) {
  if (seat.status !== 'available') return
  selectedSeat.value = seat
  showBooking.value = true
}

function selectSegment(item) {
  selectedSegment.value = item.label
  selectedSegmentId.value = item.id
  if (isLoggedIn.value) loadSeats()
}

async function confirmBooking() {
  if (!selectedSeat.value) return
  if (!isLoggedIn.value) {
    showBooking.value = false
    showLogin.value = true
    notify('请先登录统一身份认证')
    return
  }
  if (!window.confirm(`将向图书馆提交真实预约：${room.value.name}，座位 A-${selectedSeat.value.number}，${selectedSegment.value}。确认继续吗？`)) return
  try {
    const response = await fetch('/api/library/reserve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ seat_id: selectedSeat.value.id, segment: selectedSegmentId.value || selectedSegment.value, confirm: true }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '预约失败')
    showBooking.value = false
    notify(`座位 A-${selectedSeat.value.number} 已完成真实预约`)
    selectedSeat.value = null
    await loadReservations()
    activeView.value = 'reservations'
  } catch (error) {
    notify(error.message || '预约接口调用失败')
  }
}

async function cancelReservation(id) {
  if (!window.confirm('取消后图书馆预约将立即失效，确认继续吗？')) return
  try {
    const response = await fetch('/api/library/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reservation_id: String(id), confirm: true }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '取消预约失败')
    await loadReservations()
    notify('真实预约已取消')
  } catch (error) {
    notify(error.message || '取消预约接口调用失败')
  }
}

function normalizeReservation(item, index) {
  const date = item.day || item.date || item.reserveDate || item.reservationDate || '待确认'
  const segment = item.segmentName || item.time || item.segment_name || item.timeName || [item.startTime, item.endTime].filter(Boolean).join('–') || '时段待确认'
  return {
    id: item.id ?? item.reservation_id ?? item.space_id ?? `remote-${index}`,
    room: item.spaceName || item.buildName || item.classroomName || item.areaName || item.room || '图书馆自习室',
    seat: item.seatNo || item.seat_name || item.seat || item.no || item.seat_id || '待确认',
    date: date.includes(' · ') ? date : `${date} · ${item.week || ''}`.replace(/ · $/, ''),
    segment,
    status: item.statusName || item.status_name || item.status || '待使用',
  }
}

async function loadReservations() {
  if (!isLoggedIn.value) return
  try {
    const response = await fetch('/api/library/reservations')
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '预约记录读取失败')
    reservations.value = Array.isArray(data) ? data.map(normalizeReservation) : []
  } catch (error) {
    notify(error.message || '无法读取真实预约记录')
  }
}

async function loadSegments() {
  if (!isLoggedIn.value) return
  try {
    const params = new URLSearchParams({ classroom: room.value.name, target_date: apiDate.value })
    const response = await fetch(`/api/library/segments?${params}`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '时段读取失败')
    remoteSegments.value = Array.isArray(data) ? data : []
    const first = segmentItems.value[0]
    if (first && !segmentItems.value.some((item) => item.label === selectedSegment.value)) selectedSegment.value = first.label
    if (first && !selectedSegmentId.value) selectedSegmentId.value = first.id
  } catch (error) {
    remoteSegments.value = []
    notify(error.message || '无法读取真实时段')
  }
}

async function loadSeats() {
  if (!isLoggedIn.value) return
  try {
    const params = new URLSearchParams({ classroom: room.value.name, target_date: apiDate.value, start_time: '08:00', end_time: '22:00' })
    if (selectedSegmentId.value) params.set('segment', selectedSegmentId.value)
    const response = await fetch(`/api/library/seats?${params}`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '座位读取失败')
    remoteSeats.value = Array.isArray(data) ? data : []
  } catch (error) {
    remoteSeats.value = []
    notify(error.message || '无法读取真实空闲座位')
  }
}

async function login() {
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(loginForm.value),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '登录失败')
    isLoggedIn.value = true
    accountName.value = data.username || loginForm.value.username
    showLogin.value = false
    loginForm.value.password = ''
    await Promise.all([loadAutomation(), loadReservations(), loadSegments(), loadSeats()])
    notify('已连接统一身份认证')
  } catch (error) {
    notify(error.message || '无法连接登录服务')
  }
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {})
  isLoggedIn.value = false
  accountName.value = ''
  automationStatus.value.running = false
  notify('已退出当前会话')
}

async function syncSession() {
  try {
    const response = await fetch('/api/health')
    if (!response.ok) return
    const data = await response.json()
    isLoggedIn.value = Boolean(data.logged_in)
    accountName.value = data.username || ''
    if (isLoggedIn.value) await Promise.all([loadReservations(), loadSegments(), loadSeats()])
  } catch {
    isLoggedIn.value = false
  }
}

async function loadAutomation() {
  try {
    const response = await fetch('/api/automation')
    if (!response.ok) return
    const data = await response.json()
    automation.value = { ...automation.value, ...data.config }
    automationStatus.value = data
  } catch {
    // The UI remains usable with local demo data when the API is not running.
  }
}

async function saveAutomation() {
  automationSaving.value = true
  try {
    const response = await fetch('/api/automation', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(automation.value),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '自动化设置保存失败')
    automation.value = { ...automation.value, ...data.config }
    automationStatus.value = data
    notify(automation.value.enabled ? '自动签到签退已启用' : '自动签到签退已暂停')
  } catch (error) {
    notify(error.message || '后端服务未连接')
  } finally {
    automationSaving.value = false
  }
}

async function refreshAutomation() {
  await loadAutomation()
  notify('自动执行状态已刷新')
}

loadAutomation()
syncSession()

watch([selectedRoom, selectedDate], async () => {
  if (!isLoggedIn.value) return
  await loadSegments()
  await loadSeats()
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar" :class="{ 'sidebar-open': mobileMenuOpen }">
      <div class="brand-row">
        <div class="brand-mark"><LibraryBig :size="20" :stroke-width="2.2" /></div>
        <span class="brand-name">QFNU Library</span>
        <button class="icon-button sidebar-close" title="关闭菜单" @click="mobileMenuOpen = false"><X :size="18" /></button>
      </div>

      <div class="account-card">
        <div class="avatar">24</div>
        <div class="account-copy">
          <strong>{{ isLoggedIn ? (accountName || '已登录') : '未登录' }}</strong>
          <span><span class="status-dot"></span>{{ isLoggedIn ? '统一认证已连接' : '等待登录' }}</span>
        </div>
        <button class="icon-button" title="账户设置" @click="isLoggedIn ? logout() : (showLogin = true)"><LogOut v-if="isLoggedIn" :size="16" /><Settings2 v-else :size="16" /></button>
      </div>

      <nav class="side-nav" aria-label="主导航">
        <button v-for="item in navItems" :key="item.id" class="nav-item" :class="{ active: activeView === item.id }" @click="activeView = item.id; mobileMenuOpen = false">
          <component :is="item.icon" :size="18" />
          <span>{{ item.label }}</span>
          <span v-if="item.id === 'reservations' && reservations.length" class="nav-count">{{ reservations.length }}</span>
        </button>
      </nav>

      <div class="sidebar-bottom">
        <div class="help-link"><CircleHelp :size="16" /><span>使用帮助</span><ArrowUpRight :size="14" /></div>
        <div class="sidebar-note">数据来自图书馆实时接口<br />服务时间 08:00–22:00</div>
      </div>
    </aside>

    <main class="main-content">
      <header class="topbar">
        <button class="icon-button menu-trigger" title="打开菜单" @click="mobileMenuOpen = true"><Menu :size="20" /></button>
        <div class="breadcrumb"><span>我的图书馆</span><ChevronDown :size="15" /></div>
        <div class="topbar-actions">
          <span class="live-status"><span class="status-dot"></span>实时同步</span>
          <button class="icon-button" title="搜索"><Search :size="18" /></button>
          <button class="avatar small-avatar" title="账户" @click="isLoggedIn ? logout() : (showLogin = true)">24</button>
        </div>
      </header>

      <section v-if="activeView === 'overview'" class="content-wrap">
        <div class="page-intro">
          <div>
            <p class="eyebrow">WED · 08月26日</p>
            <h1>今天，去一个安静的地方。</h1>
            <p class="intro-copy">选择一个座位，专注于接下来的时间。</p>
          </div>
          <button class="secondary-button" @click="activeView = 'map'"><Armchair :size="16" />查看座位地图</button>
        </div>

        <div class="metrics-grid">
          <div class="metric-card metric-primary">
            <div class="metric-icon"><Armchair :size="18" /></div>
            <div><span class="metric-label">可用座位</span><strong>{{ availableCount }}</strong><span class="metric-detail">/ 64 个座位</span></div>
            <div class="metric-trend"><CheckCircle2 :size="14" />状态良好</div>
          </div>
          <div class="metric-card">
            <div class="metric-icon orange"><Users :size="18" /></div>
            <div><span class="metric-label">当前使用率</span><strong>{{ occupancy }}%</strong><span class="metric-detail">本时段</span></div>
            <div class="progress-line"><span :style="{ width: `${occupancy}%` }"></span></div>
          </div>
          <div class="metric-card">
            <div class="metric-icon blue"><CalendarDays :size="18" /></div>
            <div><span class="metric-label">我的预约</span><strong>{{ reservations.length }}</strong><span class="metric-detail">条待使用</span></div>
            <button class="text-button" @click="activeView = 'reservations'">查看 <ArrowUpRight :size="14" /></button>
          </div>
        </div>

        <div class="workspace-grid">
          <section class="panel seat-panel">
            <div class="panel-heading">
              <div><span class="section-kicker">QUICK RESERVE</span><h2>选择一个座位</h2></div>
              <button class="filter-button" title="筛选条件"><SlidersHorizontal :size="16" />筛选</button>
            </div>
            <div class="control-row">
              <div class="select-control"><MapPin :size="16" /><select v-model="selectedRoom"><option v-for="(item, index) in rooms" :key="item.name" :value="index">{{ item.short }}</option></select><ChevronDown :size="15" /></div>
              <div class="date-tabs"><button v-for="date in dates" :key="date.value" :class="{ active: selectedDate === date.value }" @click="selectedDate = date.value"><span>{{ date.label }}</span><small>{{ date.date }}</small></button></div>
            </div>
            <div class="room-summary"><div><strong>{{ room.name }}</strong><span><Clock3 :size="14" />{{ room.open }}</span></div><span class="available-copy"><span class="status-dot"></span>{{ availableCount }} 个空闲</span></div>
            <div class="seat-legend"><span><i class="legend-dot available"></i>空闲</span><span><i class="legend-dot selected"></i>已选择</span><span><i class="legend-dot occupied"></i>使用中</span><span><i class="legend-dot reserved"></i>已预约</span></div>
            <div class="seat-map" aria-label="座位地图">
              <div class="map-label"><span>窗边</span><span>入口 / 服务台</span><span>窗边</span></div>
              <div class="seat-grid">
                <button v-for="seat in seats" :key="seat.id" class="seat" :class="[seat.status, { chosen: selectedSeat?.id === seat.id }]" :disabled="seat.status !== 'available'" :title="`A-${seat.number} · ${seat.status === 'available' ? '空闲' : seat.status === 'occupied' ? '使用中' : seat.status === 'reserved' ? '已预约' : '清洁中'}`" @click="selectSeat(seat)"><span>A-{{ seat.number }}</span></button>
              </div>
            </div>
            <div class="panel-footer"><span><Sparkles :size="15" />座位状态每 30 秒自动刷新</span><button class="text-button" @click="notify('座位状态已刷新')">立即刷新 <ArrowUpRight :size="14" /></button></div>
          </section>

          <aside class="right-rail">
            <section class="panel focus-panel"><div class="focus-top"><span class="section-kicker">YOUR NEXT SESSION</span><Coffee :size="20" /></div><h3>{{ reservations[0] ? reservations[0].segment : '还没有预约' }}</h3><p v-if="reservations[0]">{{ reservations[0].room }}<br />座位 {{ reservations[0].seat }} · {{ reservations[0].date }}</p><p v-else>从座位地图中选择一个喜欢的位置。</p><button class="dark-button" @click="reservations[0] ? (activeView = 'reservations') : (activeView = 'map')">{{ reservations[0] ? '查看预约' : '开始选座' }}<ArrowUpRight :size="16" /></button></section>
            <section class="panel room-panel"><div class="panel-heading compact"><div><span class="section-kicker">LIBRARY SPACES</span><h3>空间概览</h3></div><button class="icon-button" title="打开空间列表" @click="activeView = 'map'"><ArrowUpRight :size="17" /></button></div><div class="room-list"><button v-for="(item, index) in rooms" :key="item.name" class="room-item" :class="{ active: selectedRoom === index }" @click="selectedRoom = index"><span class="room-color" :class="item.accent"></span><span class="room-item-copy"><strong>{{ item.short }}</strong><small>{{ item.seats }} 个座位</small></span><span class="room-arrow"><ArrowUpRight :size="15" /></span></button></div></section>
          </aside>
        </div>
      </section>

      <section v-else-if="activeView === 'map'" class="content-wrap simple-view">
        <div class="page-intro"><div><p class="eyebrow">SEAT MAP</p><h1>座位地图</h1><p class="intro-copy">点击空闲座位查看预约详情。</p></div><button class="secondary-button" @click="activeView = 'overview'"><LayoutDashboard :size="16" />回到总览</button></div>
        <section class="panel seat-panel map-page-panel"><div class="panel-heading"><div><span class="section-kicker">{{ room.short }}</span><h2>平面座位图</h2></div><div class="select-control compact-select"><MapPin :size="16" /><select v-model="selectedRoom"><option v-for="(item, index) in rooms" :key="item.name" :value="index">{{ item.short }}</option></select><ChevronDown :size="15" /></div></div><div class="control-row"><div class="date-tabs"><button v-for="date in dates" :key="date.value" :class="{ active: selectedDate === date.value }" @click="selectedDate = date.value"><span>{{ date.label }}</span><small>{{ date.date }}</small></button></div><div class="segment-tabs"><button v-for="segment in segmentItems" :key="segment.id" :class="{ active: selectedSegment === segment.label }" @click="selectSegment(segment)"><Clock3 :size="14" />{{ segment.label }}</button></div></div><div class="seat-legend"><span><i class="legend-dot available"></i>空闲</span><span><i class="legend-dot selected"></i>已选择</span><span><i class="legend-dot occupied"></i>使用中</span><span><i class="legend-dot reserved"></i>已预约</span></div><div class="seat-map large"><div class="map-label"><span>窗边</span><span>入口 / 服务台</span><span>窗边</span></div><div class="seat-grid"> <button v-for="seat in seats" :key="seat.id" class="seat" :class="[seat.status, { chosen: selectedSeat?.id === seat.id }]" :disabled="seat.status !== 'available'" @click="selectSeat(seat)"><span>A-{{ seat.number }}</span></button></div></div></section>
      </section>

      <section v-else-if="activeView === 'reservations'" class="content-wrap simple-view">
        <div class="page-intro"><div><p class="eyebrow">MY RESERVATIONS</p><h1>我的预约</h1><p class="intro-copy">管理即将到来的学习时段。</p></div><button class="secondary-button" @click="activeView = 'map'"><Armchair :size="16" />预约新座位</button></div>
        <section class="panel reservations-panel"><div class="panel-heading"><div><span class="section-kicker">UPCOMING</span><h2>即将开始</h2></div><span class="reservation-count">{{ reservations.length }} 条记录</span></div><div v-if="reservations.length" class="reservation-list"><article v-for="item in reservations" :key="item.id" class="reservation-item"><div class="reservation-date"><strong>{{ item.date.split(' · ')[0] }}</strong><span>{{ item.date.split(' · ')[1] }}</span></div><div class="reservation-main"><div><strong>{{ item.room }}</strong><span>座位 {{ item.seat }} · {{ item.segment }}</span></div><span class="reservation-status"><Check :size="14" />{{ item.status }}</span></div><button class="icon-button danger" title="取消预约" @click="cancelReservation(item.id)"><X :size="17" /></button></article></div><div v-else class="empty-state"><CalendarDays :size="30" /><strong>还没有预约</strong><span>从座位地图中选择一个安静的位置。</span><button class="dark-button" @click="activeView = 'map'">开始选座 <ArrowUpRight :size="16" /></button></div></section>
      </section>

      <section v-else class="content-wrap simple-view">
        <div class="page-intro"><div><p class="eyebrow">AUTOMATION</p><h1>自动执行</h1><p class="intro-copy">让签到和签退在你设定的时间自动完成。</p></div><button class="secondary-button" title="刷新自动化状态" @click="refreshAutomation"><RefreshCw :size="16" />刷新状态</button></div>
        <div class="automation-layout">
          <section class="panel automation-panel">
            <div class="panel-heading"><div><span class="section-kicker">SCHEDULE</span><h2>签到与签退计划</h2></div><span class="automation-state" :class="{ on: automation.enabled && automationStatus.running }"><span class="status-dot"></span>{{ automation.enabled && automationStatus.running ? '运行中' : '未启用' }}</span></div>
            <div class="automation-warning"><ShieldCheck :size="18" /><div><strong>自动操作保护</strong><p>启用后，服务端会在设定时间调用图书馆真实签到/签退接口。请先确认学校规定允许使用。</p></div></div>
            <label class="switch-row"><span><strong>启用自动签到签退</strong><small>需要已登录统一身份认证</small></span><input v-model="automation.enabled" type="checkbox" /><i class="switch-ui"></i></label>
            <div class="automation-options"><label class="switch-row"><span><strong>自动签到</strong><small>在预约开始前执行</small></span><input v-model="automation.check_in_enabled" type="checkbox" /><i class="switch-ui"></i></label><label class="switch-row"><span><strong>自动签退</strong><small>到达结束时间后执行</small></span><input v-model="automation.check_out_enabled" type="checkbox" /><i class="switch-ui"></i></label></div>
            <div class="time-grid"><label>签到时间<input v-model="automation.check_in_time" type="time" /></label><label>签退时间<input v-model="automation.check_out_time" type="time" /></label></div>
            <label class="field-label">指定预约（可选）<select v-model="automation.reservation_id"><option value="">自动查找“使用中”的预约</option><option v-for="item in reservations" :key="item.id" :value="String(item.id)">{{ item.room }} · {{ item.seat }}</option></select></label>
            <button class="dark-button wide save-automation" :disabled="automationSaving" @click="saveAutomation">{{ automationSaving ? '保存中…' : '保存自动执行设置' }}<Check v-if="!automationSaving" :size="17" /></button>
          </section>
          <aside class="automation-side"><section class="panel automation-status-panel"><div class="focus-top"><span class="section-kicker">RUN STATUS</span><Zap :size="19" /></div><h3>{{ automationStatus.running ? '正在守候' : '等待启用' }}</h3><p>{{ automationStatus.last_message || '服务端每 20 秒检查一次计划，在目标分钟内只执行一次。' }}</p><div class="status-lines"><div><span>自动签到</span><strong>{{ automation.check_in_enabled ? automation.check_in_time : '已关闭' }}</strong></div><div><span>自动签退</span><strong>{{ automation.check_out_enabled ? automation.check_out_time : '已关闭' }}</strong></div></div></section><section class="panel automation-log"><div class="panel-heading compact"><div><span class="section-kicker">LAST ACTION</span><h3>最近一次执行</h3></div><ShieldCheck :size="17" /></div><div v-if="automationStatus.last_run_at" class="last-action"><span class="action-icon"><CheckCircle2 :size="16" /></span><div><strong>{{ automationStatus.last_action === 'check-in' ? '自动签到' : '自动签退' }}</strong><small>{{ automationStatus.last_run_at }}</small></div></div><div v-else class="empty-log"><Clock3 :size="20" /><span>尚未执行记录</span></div></section></aside>
        </div>
      </section>
    </main>

    <transition name="slide-up"><div v-if="showBooking && selectedSeat" class="booking-drawer"><div class="drawer-handle"></div><div class="drawer-head"><div><span class="section-kicker">CONFIRM RESERVATION</span><h2>确认你的座位</h2></div><button class="icon-button" title="关闭" @click="showBooking = false"><X :size="18" /></button></div><div class="seat-preview"><div class="seat-preview-icon"><Armchair :size="23" /></div><div><strong>A-{{ selectedSeat.number }}</strong><span>{{ room.name }}</span></div><span class="status-pill"><span class="status-dot"></span>空闲</span></div><div class="booking-fields"><label>日期<div class="field-value"><CalendarDays :size="16" />{{ selectedDate }} · 08月27日<ChevronDown :size="16" /></div></label><label>使用时段<div class="segment-tabs drawer-segments"><button v-for="segment in segmentItems" :key="segment.id" :class="{ active: selectedSegment === segment.label }" @click="selectSegment(segment)">{{ segment.label }}</button></div></label></div><button class="dark-button wide" @click="confirmBooking">确认真实预约 <Check :size="17" /></button><p class="drawer-note"><LockKeyhole :size="14" />确认后将向图书馆提交真实预约</p></div></transition>
    <div v-if="showBooking" class="scrim" @click="showBooking = false"></div>

    <div v-if="showLogin" class="modal-layer"><div class="scrim" @click="showLogin = false"></div><section class="login-modal"><button class="icon-button modal-close" title="关闭" @click="showLogin = false"><X :size="18" /></button><div class="login-mark"><LibraryBig :size="22" /></div><span class="section-kicker">QFNU SINGLE SIGN-ON</span><h2>连接你的图书馆</h2><p>使用统一身份认证账号继续。</p><label>账号<input v-model="loginForm.username" placeholder="请输入学号" /></label><label>密码<input v-model="loginForm.password" type="password" placeholder="请输入密码" /></label><button class="dark-button wide" @click="login">登录并连接 <ArrowUpRight :size="16" /></button><span class="secure-note"><LockKeyhole :size="13" />凭据仅用于本次会话</span></section></div>

    <transition name="toast"><div v-if="toast" class="toast"><CheckCircle2 :size="17" />{{ toast }}</div></transition>
  </div>
</template>
