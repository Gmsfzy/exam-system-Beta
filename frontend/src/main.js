import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { fas } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import './style.css'
import App from './App.vue'
import router from './router'
import { logger } from './utils/logger'



const app = createApp(App)
const pinia = createPinia()

// v5.28：Vue 渲染/生命周期异常统一进克制上报（仅 ERROR 回传，去重+限流已内置）
app.config.errorHandler = (err, _instance, info) => {
  logger.error(`Vue error (${info})`, err instanceof Error ? err : new Error(String(err)))
}

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

library.add(fas)
app.component('FontAwesomeIcon', FontAwesomeIcon)

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })

import { useThemeStore } from './stores/theme'
const theme = useThemeStore()

if (theme.isDark) {
  document.documentElement.classList.add('dark')
}

app.mount('#app')