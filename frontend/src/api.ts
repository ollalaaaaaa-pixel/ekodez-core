export function apiBaseForHostname(hostname: string, protocol: string = 'http:'): string {
  const backendProtocol = protocol === 'https:' ? 'https:' : 'http:'
  return `${backendProtocol}//${hostname}:8000`
}

export const API = apiBaseForHostname(window.location.hostname, window.location.protocol)
