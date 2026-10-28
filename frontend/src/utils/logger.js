/**
 * 前端错误「克制上报」（v5.28）
 *
 * 设计边界（与 utils/logger.py 的 vue3_logger、api/log_routes.py 的 /api/logs/vue 配套）：
 * - 仅 ERROR 级（未捕获异常 / 未处理 Promise 拒绝 / Vue 渲染错误）回传服务器落盘 logs/vue3.log；
 *   debug/info/warning 只打印浏览器 console，绝不产生网络流量（旧版全量上报会刷爆限流与日志）。
 * - 同错误签名 10 秒窗口去重：错误风暴（如循环内反复抛错）只报首条。
 * - 队列封顶 50 条，溢出丢最旧；发送失败直接丢弃本轮，绝不无限重推（离线不涨内存）。
 * - 无 token（门户/登录页匿名访问）时静默跳过，后端本来也要求登录（401）。
 * 后端护栏已具备：登录鉴权 + 30 次/分钟限流 + 2000 字符截断 + 换行剥离防日志注入。
 */
const LOG_LEVEL = {
  DEBUG: 0,
  INFO: 1,
  WARNING: 2,
  ERROR: 3
};

const REPORT_URL = '/api/logs/vue';
const DEDUP_WINDOW_MS = 10000;   // 同签名错误去重窗口
const QUEUE_LIMIT = 50;          // 待报队列上限，溢出丢最旧
const MAX_SEEN_ENTRIES = 200;    // 去重表上限，防长时间运行内存缓涨

class Logger {
  constructor() {
    this.level = process.env.NODE_ENV === 'production' ? LOG_LEVEL.INFO : LOG_LEVEL.DEBUG;
    this.queue = [];
    this.sending = false;
    this.lastSeen = new Map(); // 错误签名 -> 上次上报时间戳
  }

  debug(message, data = {}) {
    if (this.level <= LOG_LEVEL.DEBUG) console.debug('%c[DEBUG]', 'color: #3B82F6', message, data);
  }

  info(message, data = {}) {
    if (this.level <= LOG_LEVEL.INFO) console.info('%c[INFO]', 'color: #22C55E', message, data);
  }

  warning(message, data = {}) {
    if (this.level <= LOG_LEVEL.WARNING) console.warn('%c[WARNING]', 'color: #F59E0B', message, data);
  }

  error(message, error = {}, data = {}) {
    console.error('%c[ERROR]', 'color: #EF4444', message, error, data);
    this.report({
      level: 'ERROR',
      message,
      data,
      stack: error && error.stack,
      errorMessage: error && error.message
    });
  }

  // 仅 ERROR 走网络回传；签名去重 + 队列封顶，绝不清空业务代码里的 console 输出
  report(entry) {
    const token = localStorage.getItem('token');
    if (!token) return; // 匿名页面不上报（后端亦要求登录）
    const sig = `${entry.message}|${(entry.stack || '').slice(0, 120)}`;
    const now = Date.now();
    const last = this.lastSeen.get(sig) || 0;
    if (now - last < DEDUP_WINDOW_MS) return;
    this.lastSeen.set(sig, now);
    if (this.lastSeen.size > MAX_SEEN_ENTRIES) {
      // 简单防涨：超限时清掉最早一半（Map 保持插入序）
      const cut = Math.floor(this.lastSeen.size / 2);
      for (const k of this.lastSeen.keys()) {
        this.lastSeen.delete(k);
        if (--cut <= 0) break;
      }
    }
    if (this.queue.length >= QUEUE_LIMIT) this.queue.shift();
    this.queue.push({ ...entry, timestamp: now });
    this.flush();
  }

  async flush() {
    if (this.sending) return;
    this.sending = true;
    while (this.queue.length > 0) {
      const log = this.queue.shift();
      try {
        const response = await fetch(REPORT_URL, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${localStorage.getItem('token') || ''}`
          },
          body: JSON.stringify({
            level: log.level,
            message: log.message,
            data: log.data,
            component: (log.data && log.data.component) || '',
            stack: log.stack || '',
            url: window.location.href,
            timestamp: new Date(log.timestamp).toISOString(),
            userAgent: navigator.userAgent
          })
        });
        // 非 2xx（401 过期 / 429 限流）视为放弃本条，不重试，避免打爆后端
        if (!response.ok && response.status !== 429) {
          console.warn('[logger] 上报被拒:', response.status);
        }
      } catch (e) {
        // 网络故障：本条直接丢弃，离线期间不无限积压
        break;
      }
    }
    this.sending = false;
  }
}

export const logger = new Logger();

// 模块加载即注册全局钩子：浏览器端错误后端不可见，这里补上唯一的观测口
window.addEventListener('error', (event) => {
  logger.error('Global error', event.error || new Error(event.message), {
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
    source: 'global'
  });
});

window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason instanceof Error
    ? event.reason
    : new Error(String((event.reason && event.reason.message) || event.reason || 'unhandled rejection'));
  logger.error('Unhandled promise rejection', reason, { source: 'promise' });
});

export function logComponent(componentName) {
  return {
    debug: (message, data = {}) => logger.debug(message, { ...data, component: componentName }),
    info: (message, data = {}) => logger.info(message, { ...data, component: componentName }),
    warning: (message, data = {}) => logger.warning(message, { ...data, component: componentName }),
    error: (message, error = {}, data = {}) => logger.error(message, error, { ...data, component: componentName })
  };
}
