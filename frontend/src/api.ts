export function apiBaseForHostname(hostname: string): string {
  return `http://${hostname}:8000`
}

export const API = apiBaseForHostname(window.location.hostname)
