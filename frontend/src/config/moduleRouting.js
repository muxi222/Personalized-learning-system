/**
 * 模块化智能路由配置
 *
 * 根据学科自动路由到对应的后端模块
 */

// 学科到模块的映射
export const SUBJECT_TO_MODULE = {
  // RPJ 模块 (6001): 语文、英语、政治
  chinese: 'rpj',
  english: 'rpj',
  politics: 'rpj',

  // XMX 模块 (6002): 经济学
  economics: 'xmx',

  // WZY 模块 (6003): 数学、物理
  math: 'wzy',
  physics: 'wzy',

  // WZM 模块 (6004): 化学
  chemistry: 'wzm',

  // TONY 模块 (6005): 历史、地理、其他
  history: 'tony',
  geography: 'tony',
  other: 'tony',
}

// 模块端口映射
export const MODULE_PORTS = {
  default: 6100,  // 默认模块 - 处理跨学科查询（6000 在浏览器不安全端口黑名单中）
  rpj: 6001,
  xmx: 6002,
  wzy: 6003,
  wzm: 6004,
  tony: 6005,
}

// 模块描述（用于显示）
export const MODULE_DESCRIPTIONS = {
  rpj: '语文、英语、政治',
  xmx: '经济学',
  wzy: '数学、物理',
  wzm: '化学',
  tony: '历史、地理、其他',
}

// 学科名称（中文）
export const SUBJECT_NAMES_CN = {
  chinese: '语文',
  english: '英语',
  politics: '政治',
  economics: '经济学',
  math: '数学',
  physics: '物理',
  chemistry: '化学',
  history: '历史',
  geography: '地理',
  other: '其他',
}

// 学科图标（emoji）
export const SUBJECT_ICONS = {
  chinese: '📖',
  english: '🔤',
  politics: '🏛️',
  economics: '💹',
  math: '📐',
  physics: '⚡',
  chemistry: '🧪',
  history: '📜',
  geography: '🗺️',
  other: '📚',
}

/**
 * 根据学科获取对应的模块名
 * @param {string} subject - 学科名称 (如 'math', 'chinese')，如果为空或undefined则返回default模块
 * @returns {string} 模块名称 (如 'wzy', 'rpj', 'default')
 */
export function getModuleBySubject(subject) {
  // 如果没有指定学科，使用默认模块（跨学科查询）
  if (!subject) {
    console.log('No subject specified, using default module for cross-subject query')
    return 'default'
  }

  const module = SUBJECT_TO_MODULE[subject]
  if (!module) {
    console.warn(`Unknown subject: ${subject}, fallback to 'default' module`)
    return 'default' // 未知学科使用默认模块
  }
  return module
}

/**
 * 根据学科获取 API 基础 URL
 * @param {string} subject - 学科名称（null 表示使用 default 模块）
 * @returns {string} API 基础 URL (如 '/api/rpj' 或 '/api/v1' 对于 default 模块)
 *
 * 注意：返回相对路径，通过 Vite proxy 转发到实际的后端模块端口
 * 例如：'/api/rpj' 会被转发到 'http://localhost:6001/api'
 *      '/api/v1' 会被转发到 'http://localhost:6100/api/v1' (default 模块)
 */
export function getApiBaseUrl(subject) {
  const module = getModuleBySubject(subject)
  // default 模块使用 /api/v1 路径（不带模块前缀）
  if (module === 'default') {
    return '/api/v1'
  }
  // 其他模块使用 /api/{module} 路径
  return `/api/${module}`
}

/**
 * 根据学科获取完整的 API URL
 * @param {string} subject - 学科名称
 * @param {string} path - API 路径 (如 '/v1/questions')
 * @returns {string} 完整的 API URL (相对路径，如 '/api/rpj/v1/questions')
 *
 * 注意：返回相对路径，通过 Vite proxy 转发
 */
export function getFullApiUrl(subject, path) {
  const baseUrl = getApiBaseUrl(subject)
  const cleanPath = path.startsWith('/') ? path : `/${path}`
  return `${baseUrl}${cleanPath}`
}

/**
 * 获取健康检查 URL
 * @param {string} module - 模块名称
 * @returns {string} 健康检查 URL (相对路径)
 *
 * 注意：返回相对路径，通过 Vite proxy 转发
 * 健康检查路径格式：/health/{module}，会被转发到对应端口的 /health
 */
export function getHealthCheckUrl(module) {
  // Vite proxy 会将 /health/{module} 转发到对应端口的 /health
  return `/health/${module}`
}

/**
 * 获取所有模块的健康检查 URL 列表
 * @returns {Object} { module: healthCheckUrl }
 */
export function getAllHealthCheckUrls() {
  const urls = {}
  Object.keys(MODULE_PORTS).forEach(module => {
    urls[module] = getHealthCheckUrl(module)
  })
  return urls
}

/**
 * 获取学科的完整信息
 * @param {string} subject - 学科名称
 * @returns {Object} 学科信息 { subject, name, icon, module, port, baseUrl }
 */
export function getSubjectInfo(subject) {
  const module = getModuleBySubject(subject)
  return {
    subject,
    name: SUBJECT_NAMES_CN[subject] || subject,
    icon: SUBJECT_ICONS[subject] || '📚',
    module,
    port: MODULE_PORTS[module],
    baseUrl: getApiBaseUrl(subject),
    moduleDescription: MODULE_DESCRIPTIONS[module],
  }
}

/**
 * 获取所有支持的学科列表
 * @returns {Array} 学科信息数组
 */
export function getAllSubjects() {
  return Object.keys(SUBJECT_TO_MODULE).map(subject => getSubjectInfo(subject))
}

/**
 * 按模块分组获取学科
 * @returns {Object} { module: [subjects] }
 */
export function getSubjectsByModule() {
  const grouped = {}
  Object.keys(MODULE_PORTS).forEach(module => {
    grouped[module] = []
  })

  Object.entries(SUBJECT_TO_MODULE).forEach(([subject, module]) => {
    const info = getSubjectInfo(subject)
    grouped[module].push(info)
  })

  return grouped
}

/**
 * 验证学科是否有效
 * @param {string} subject - 学科名称
 * @returns {boolean} 是否有效
 */
export function isValidSubject(subject) {
  return subject in SUBJECT_TO_MODULE
}

/**
 * 获取模块支持的学科列表
 * @param {string} module - 模块名称
 * @returns {Array} 学科列表
 */
export function getSubjectsByModuleName(module) {
  return Object.entries(SUBJECT_TO_MODULE)
    .filter(([_, mod]) => mod === module)
    .map(([subject]) => subject)
}

// 默认导出
export default {
  SUBJECT_TO_MODULE,
  MODULE_PORTS,
  MODULE_DESCRIPTIONS,
  SUBJECT_NAMES_CN,
  SUBJECT_ICONS,
  getModuleBySubject,
  getApiBaseUrl,
  getFullApiUrl,
  getHealthCheckUrl,
  getAllHealthCheckUrls,
  getSubjectInfo,
  getAllSubjects,
  getSubjectsByModule,
  isValidSubject,
  getSubjectsByModuleName,
}
