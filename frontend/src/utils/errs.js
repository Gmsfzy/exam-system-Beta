// axios 错误的人话解释：把「接口不存在 / 服务没起 / 后端给了业务报错」三种情状分开说。
// 之所以要抽出来：页面只报一个状态码，用户既不知道该重试还是该刷新构建，
// 维护者也分不清是前端路径写错还是后端进程没重启（404 两种都可能）。
export function errTip(e) {
  const resp = e?.response
  if (!resp) {
    // 没有 response 只有两种：请求没发出去（服务没起 / 网络断）或超时被掐
    return e?.code === 'ECONNABORTED'
      ? '请求超时：接口处理太久，请稍后重试或缩小范围'
      : '连不上后端，请确认服务已启动'
  }
  const s = resp.status
  if (s === 404) return '后端没有这个接口（404）：若刚上线新功能，多半是后端进程没重启'
  if (s === 401) return resp.data?.message || '登录已过期，请重新登录'
  return resp.data?.message || `请求失败（${s}）`
}
