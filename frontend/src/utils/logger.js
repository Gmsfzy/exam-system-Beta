const LOG_LEVEL = {
  DEBUG: 0,
  INFO: 1,
  WARNING: 2,
  ERROR: 3
};

class Logger {
  constructor() {
    this.level = process.env.NODE_ENV === 'production' ? LOG_LEVEL.INFO : LOG_LEVEL.DEBUG;
    this.isSending = false;
    this.queue = [];
  }

  debug(message, data = {}) {
    if (this.level <= LOG_LEVEL.DEBUG) {
      console.debug(`%c[DEBUG]`, 'color: #3B82F6', message, data);
      this.queueLog('DEBUG', message, data);
    }
  }

  info(message, data = {}) {
    if (this.level <= LOG_LEVEL.INFO) {
      console.info(`%c[INFO]`, 'color: #22C55E', message, data);
      this.queueLog('INFO', message, data);
    }
  }

  warning(message, data = {}) {
    if (this.level <= LOG_LEVEL.WARNING) {
      console.warn(`%c[WARNING]`, 'color: #F59E0B', message, data);
      this.queueLog('WARNING', message, data);
    }
  }

  error(message, error = {}, data = {}) {
    console.error(`%c[ERROR]`, 'color: #EF4444', message, error, data);
    this.queueLog('ERROR', message, {
      ...data,
      stack: error.stack,
      errorMessage: error.message
    });
  }

  queueLog(level, message, data) {
    this.queue.push({ level, message, data, timestamp: Date.now() });
    if (!this.isSending && this.queue.length > 0) {
      this.sendLogs();
    }
  }

  async sendLogs() {
    if (this.isSending) return;
    this.isSending = true;
    
    const logsToSend = [...this.queue];
    this.queue = [];

    try {
      const token = localStorage.getItem('token');
      for (const log of logsToSend) {
        await fetch('/api/logs/vue', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': token ? `Bearer ${token}` : ''
          },
          body: JSON.stringify({
            level: log.level,
            message: log.message,
            data: log.data,
            component: log.data.component || '',
            url: window.location.href,
            timestamp: new Date(log.timestamp).toISOString(),
            userAgent: navigator.userAgent
          })
        });
      }
    } catch (error) {
      console.error('Failed to send logs:', error);
      this.queue.unshift(...logsToSend);
    } finally {
      this.isSending = false;
      if (this.queue.length > 0) {
        setTimeout(() => this.sendLogs(), 1000);
      }
    }
  }
}

export const logger = new Logger();

window.addEventListener('error', (event) => {
  logger.error('Global error', event.error, {
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
    source: 'global'
  });
});

window.addEventListener('unhandledrejection', (event) => {
  logger.error('Unhandled promise rejection', event.reason, { source: 'promise' });
});

export function logComponent(componentName) {
  return {
    debug: (message, data = {}) => logger.debug(message, { ...data, component: componentName }),
    info: (message, data = {}) => logger.info(message, { ...data, component: componentName }),
    warning: (message, data = {}) => logger.warning(message, { ...data, component: componentName }),
    error: (message, error = {}, data = {}) => logger.error(message, error, { ...data, component: componentName })
  };
}