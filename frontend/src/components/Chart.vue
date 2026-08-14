<template>
  <div ref="el" :style="{ height: height + 'px', width: '100%' }"></div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{ option: Record<string, unknown>; height?: number }>()

const el = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

onMounted(() => {
  if (el.value) {
    chart = echarts.init(el.value)
    chart.setOption(props.option)
  }
})

watch(
  () => props.option,
  (opt) => chart?.setOption(opt, { notMerge: true }),
  { deep: true }
)

onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>