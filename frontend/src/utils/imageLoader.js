/**
 * 图片加载工具函数
 * 支持带认证token的图片加载
 */

/**
 * 获取认证token
 */
export const getAuthToken = () => {
  const authStorage = localStorage.getItem('auth-storage')
  if (authStorage) {
    try {
      const { state } = JSON.parse(authStorage)
      return state?.token
    } catch (e) {
      console.error('Failed to parse auth-storage:', e)
      return null
    }
  }
  return null
}

/**
 * 加载带认证的图片并转换为blob URL
 * @param {string} imageUrl - 图片URL
 * @returns {Promise<string>} - blob URL
 */
export const loadImageWithAuth = async (imageUrl) => {
  const token = getAuthToken()
  
  // 如果是完整URL，直接使用
  if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
    return imageUrl
  }
  
  // 构建完整URL
  const fullUrl = imageUrl.startsWith('/') ? imageUrl : `/api/v1${imageUrl}`
  
  try {
    const headers = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    
    const response = await fetch(fullUrl, { headers })
    
    if (!response.ok) {
      throw new Error(`Failed to load image: ${response.status} ${response.statusText}`)
    }
    
    const blob = await response.blob()
    return URL.createObjectURL(blob)
  } catch (error) {
    console.error('Failed to load image with auth:', error)
    // 如果失败，尝试直接使用URL（开发模式）
    return fullUrl
  }
}

/**
 * 清理blob URL
 * @param {string} blobUrl - blob URL
 */
export const revokeImageBlob = (blobUrl) => {
  if (blobUrl && blobUrl.startsWith('blob:')) {
    URL.revokeObjectURL(blobUrl)
  }
}

