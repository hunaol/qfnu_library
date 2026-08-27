<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, ChevronDown, MapPin } from 'lucide-vue-next'

const props = defineProps({
  rooms: { type: Array, default: () => [] },
  modelValue: { type: Number, default: 0 },
})
const emit = defineEmits(['update:modelValue'])
const open = ref(false)
const root = ref(null)

const selectedRoom = () => props.rooms[props.modelValue] || props.rooms[0] || { short: '选择地点', name: '选择地点' }

function choose(index) {
  emit('update:modelValue', index)
  open.value = false
}

function closeOutside(event) {
  if (open.value && root.value && !root.value.contains(event.target)) open.value = false
}

onMounted(() => document.addEventListener('pointerdown', closeOutside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeOutside))
</script>

<template>
  <div ref="root" class="location-picker">
    <button class="location-trigger" type="button" :aria-expanded="open" @click="open = !open">
      <MapPin :size="18" />
      <span>{{ selectedRoom().short || selectedRoom().name }}</span>
      <ChevronDown :size="17" />
    </button>
    <div v-if="open" class="location-menu">
      <div class="location-menu-title">选择空间</div>
      <button v-for="(room, index) in rooms" :key="room.name" class="location-option" type="button" :class="{ selected: modelValue === index }" @click="choose(index)">
        <span class="location-color" :class="room.accent"></span>
        <span class="location-option-copy"><strong>{{ room.short || room.name }}</strong><small>{{ room.seats ? `${room.seats} 个座位` : room.name }}</small></span>
        <Check v-if="modelValue === index" :size="16" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.location-picker { position: relative; min-width: 230px; }
.location-trigger { width: 100%; height: 42px; display: flex; align-items: center; gap: 9px; padding: 0 12px; border: 1px solid #d6d6d8; border-radius: 10px; background: #fff; color: #1d1d1f; box-shadow: 0 1px 2px rgba(0,0,0,.03); text-align: left; transition: border-color .2s, box-shadow .2s, background .2s; }
.location-trigger:hover { background: #fafafa; }
.location-trigger:focus-visible, .location-trigger[aria-expanded='true'] { outline: 0; border-color: #0071e3; box-shadow: 0 0 0 3px rgba(0,113,227,.14); }
.location-trigger > svg:first-child { color: #6e6e73; flex: none; }
.location-trigger > span { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.location-trigger > svg:last-child { color: #86868b; flex: none; transition: transform .2s; }
.location-trigger[aria-expanded='true'] > svg:last-child { transform: rotate(180deg); }
.location-menu { position: absolute; z-index: 70; top: calc(100% + 7px); left: 0; width: min(320px, calc(100vw - 28px)); padding: 8px; border: 1px solid #dedee0; border-radius: 12px; background: rgba(255,255,255,.98); box-shadow: 0 16px 42px rgba(0,0,0,.16); backdrop-filter: blur(18px); }
.location-menu-title { padding: 7px 10px 8px; color: #86868b; font-size: 10px; }
.location-option { width: 100%; display: flex; align-items: center; gap: 10px; min-height: 46px; padding: 7px 9px; border-radius: 8px; background: transparent; text-align: left; color: #1d1d1f; }
.location-option:hover, .location-option.selected { background: #f5f5f7; }
.location-option > svg { margin-left: auto; color: #0071e3; flex: none; }
.location-color { width: 7px; height: 26px; border-radius: 4px; background: #9bd7bc; flex: none; }.location-color.blue { background: #b6cdf4; }.location-color.orange { background: #f2c27a; }.location-color.violet { background: #c9b8ed; }
.location-option-copy { min-width: 0; display: grid; gap: 3px; }.location-option-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 600; }.location-option-copy small { color: #86868b; font-size: 10px; }
@media (max-width: 760px) { .location-picker { width: 100%; min-width: 0; }.location-menu { position: fixed; left: 14px; right: 14px; top: auto; bottom: 18px; width: auto; max-height: 70vh; overflow-y: auto; } }
</style>
