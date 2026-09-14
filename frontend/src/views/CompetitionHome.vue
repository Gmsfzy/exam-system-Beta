<template>
  <CompetitionManage v-if="isTeacher" />
  <CompetitionPlaza v-else />
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import CompetitionManage from './CompetitionManage.vue'
import CompetitionPlaza from './CompetitionPlaza.vue'

const auth = useAuthStore()
const isTeacher = computed(() => auth.user?.role === 'teacher')
</script>
