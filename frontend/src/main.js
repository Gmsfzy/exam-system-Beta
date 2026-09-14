import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import { library } from '@fortawesome/fontawesome-svg-core'
import { fas } from '@fortawesome/free-solid-svg-icons'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import './style.css'
import App from './App.vue'
import router from './router'



const app = createApp(App)
const pinia = createPinia()

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

library.add(fas)
app.component('FontAwesomeIcon', FontAwesomeIcon)

app.use(pinia)
app.use(router)
app.use(ElementPlus)

import { useThemeStore } from './stores/theme'
const theme = useThemeStore()

if (theme.isDark) {
  document.documentElement.classList.add('dark')
}

app.mount('#app')