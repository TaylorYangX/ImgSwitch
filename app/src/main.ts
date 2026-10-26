import { createApp } from 'vue'
import App from './App.vue'
import { initApi } from './api'
import { i18n } from './i18n'
import { loadAll, startApp, store } from './store'
import './style.css'

createApp(App).use(i18n).mount('#app')
startApp()
initApi()
  .then(loadAll)
  .catch((e) => (store.loadError = String(e)))
