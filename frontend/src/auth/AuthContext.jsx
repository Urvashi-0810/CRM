import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, onUnauthorized, setCsrfToken } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  // undefined = still checking, null = logged out, object = logged in
  const [me, setMe] = useState(undefined)

  const refresh = useCallback(async () => {
    try {
      const data = await api('/me')
      setCsrfToken(data.csrf_token)
      setMe(data)
      return data
    } catch (error) {
      if (error.status === 401) {
        setCsrfToken(null)
        setMe(null)
        return null
      }
      throw error
    }
  }, [])

  useEffect(() => {
    refresh().catch(() => setMe(null))
    return onUnauthorized(() => {
      setCsrfToken(null)
      setMe(null)
    })
  }, [refresh])

  const login = useCallback(
    async (username, password) => {
      const data = await api('/auth/login', { method: 'POST', body: { username, password } })
      setCsrfToken(data.csrf_token)
      return refresh()
    },
    [refresh],
  )

  const logout = useCallback(async () => {
    try {
      await api('/auth/logout', { method: 'POST' })
    } finally {
      setCsrfToken(null)
      setMe(null)
    }
  }, [])

  return <AuthContext.Provider value={{ me, refresh, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
