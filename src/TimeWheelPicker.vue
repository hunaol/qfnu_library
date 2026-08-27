<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, ChevronDown, Clock3 } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: String, default: '00:00' },
})
const emit = defineEmits(['update:modelValue'])

const itemHeight = 36
const hours = Array.from({ length: 24 }, (_, index) => String(index).padStart(2, '0'))
const minutes = Array.from({ length: 60 }, (_, index) => String(index).padStart(2, '0'))
const root = ref(null)
const hourWheel = ref(null)
const minuteWheel = ref(null)
const open = ref(false)
const draftHour = ref('00')
const draftMinute = ref('00')
const timers = { hour: null, minute: null }

function readValue(value = props.modelValue) {
  const [hour = '00', minute = '00'] = String(value).split(':')
  draftHour.value = hours.includes(hour) ? hour : '00'
  draftMinute.value = minutes.includes(minute) ? minute : '00'
}

function scrollToValue(element, value, behavior = 'auto') {
  if (!element) return
  element.scrollTo({ top: Number(value) * itemHeight, behavior })
}

async function openPicker() {
  readValue()
  open.value = true
  await nextTick()
  scrollToValue(hourWheel.value, draftHour.value)
  scrollToValue(minuteWheel.value, draftMinute.value)
}

function selectValue(type, value) {
  if (type === 'hour') {
    draftHour.value = value
    scrollToValue(hourWheel.value, value, 'smooth')
  } else {
    draftMinute.value = value
    scrollToValue(minuteWheel.value, value, 'smooth')
  }
}

function handleScroll(type, event) {
  clearTimeout(timers[type])
  timers[type] = setTimeout(() => {
    const values = type === 'hour' ? hours : minutes
    const index = Math.max(0, Math.min(values.length - 1, Math.round(event.target.scrollTop / itemHeight)))
    if (type === 'hour') draftHour.value = values[index]
    else draftMinute.value = values[index]
    event.target.scrollTo({ top: index * itemHeight, behavior: 'smooth' })
  }, 90)
}

function confirm() {
  emit('update:modelValue', `${draftHour.value}:${draftMinute.value}`)
  open.value = false
}

function handleOutside(event) {
  if (open.value && root.value && !root.value.contains(event.target)) open.value = false
}

watch(() => props.modelValue, () => {
  if (!open.value) readValue()
}, { immediate: true })

onMounted(() => document.addEventListener('pointerdown', handleOutside))
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleOutside)
  clearTimeout(timers.hour)
  clearTimeout(timers.minute)
})
</script>

<template>
  <div ref="root" class="time-wheel-picker">
    <button class="time-wheel-trigger" type="button" :aria-expanded="open" @click="open ? (open = false) : openPicker()">
      <Clock3 :size="16" />
      <span>{{ modelValue }}</span>
      <ChevronDown :size="15" />
    </button>
    <div v-if="open" class="time-wheel-popover">
      <div class="time-wheel-heading"><span>选择时间</span><button type="button" @click="confirm">完成 <Check :size="14" /></button></div>
      <div class="time-wheel-body">
        <div ref="hourWheel" class="wheel-column" aria-label="小时" @scroll.passive="handleScroll('hour', $event)">
          <button v-for="hour in hours" :key="hour" type="button" :class="{ selected: draftHour === hour }" @click="selectValue('hour', hour)">{{ hour }}</button>
        </div>
        <strong>:</strong>
        <div ref="minuteWheel" class="wheel-column" aria-label="分钟" @scroll.passive="handleScroll('minute', $event)">
          <button v-for="minute in minutes" :key="minute" type="button" :class="{ selected: draftMinute === minute }" @click="selectValue('minute', minute)">{{ minute }}</button>
        </div>
        <span class="wheel-selection" aria-hidden="true"></span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.time-wheel-picker { position: relative; width: 100%; }
.time-wheel-trigger { width: 100%; height: 44px; display: flex; align-items: center; gap: 9px; padding: 0 13px; border: 1px solid #d6d6d8; border-radius: 10px; background: #fff; color: #1d1d1f; font-size: 13px; text-align: left; box-shadow: 0 1px 2px rgba(0, 0, 0, .03); }
.time-wheel-trigger:focus-visible { outline: 0; border-color: #0071e3; box-shadow: 0 0 0 3px rgba(0, 113, 227, .14); }
.time-wheel-trigger svg:first-child { color: #6e6e73; }
.time-wheel-trigger svg:last-child { margin-left: auto; color: #86868b; transition: transform .2s; }
.time-wheel-trigger[aria-expanded='true'] svg:last-child { transform: rotate(180deg); }
.time-wheel-popover { position: absolute; z-index: 80; top: calc(100% + 7px); left: 0; width: min(280px, 100%); padding: 10px 12px 12px; border: 1px solid #dedee0; border-radius: 12px; background: rgba(255, 255, 255, .98); box-shadow: 0 16px 42px rgba(0, 0, 0, .16); backdrop-filter: blur(18px); }
.time-wheel-heading { height: 32px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #ededee; color: #6e6e73; font-size: 11px; }
.time-wheel-heading button { display: inline-flex; align-items: center; gap: 4px; padding: 5px 3px; background: transparent; color: #0071e3; font-size: 11px; font-weight: 600; }
.time-wheel-body { position: relative; height: 108px; display: grid; grid-template-columns: 1fr 20px 1fr; align-items: center; margin-top: 8px; overflow: hidden; }
.time-wheel-body > strong { z-index: 2; text-align: center; font-size: 18px; }
.wheel-column { z-index: 2; height: 108px; overflow-y: auto; scroll-snap-type: y mandatory; scrollbar-width: none; padding: 36px 0; }
.wheel-column::-webkit-scrollbar { display: none; }
.wheel-column button { width: 100%; height: 36px; display: block; padding: 0; scroll-snap-align: center; background: transparent; color: #8e8e93; font-size: 16px; line-height: 36px; }
.wheel-column button.selected { color: #1d1d1f; font-weight: 600; }
.wheel-selection { position: absolute; z-index: 1; left: 0; right: 0; top: 36px; height: 36px; border-top: 1px solid #dedee0; border-bottom: 1px solid #dedee0; border-radius: 7px; background: #f5f5f7; pointer-events: none; }
@media (max-width: 760px) { .time-wheel-popover { position: fixed; left: 14px; right: 14px; top: auto; bottom: 18px; width: auto; }.time-wheel-body { height: 144px; }.wheel-column { height: 144px; padding: 54px 0; }.wheel-selection { top: 54px; } }
</style>
