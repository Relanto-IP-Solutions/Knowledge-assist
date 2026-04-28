import gdriveLogo from '../assets/gdrive-logo.png'

export function ZoomIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" style={{ flexShrink: 0 }}>
      <circle cx="24" cy="24" r="24" fill="#4A8CFF"/>
      <rect x="10" y="15" width="19" height="14" rx="3.5" fill="#fff"/>
      <path d="M29 19.5L37 15v16l-8-4.5" fill="#fff"/>
    </svg>
  )
}

export function GDriveIcon({ size = 16 }) {
  return (
    <img
      src={gdriveLogo}
      alt="Google Drive"
      width={size}
      height={size}
      style={{ flexShrink: 0, display: 'block', objectFit: 'contain' }}
    />
  )
}

export function GmailIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
      <path d="M22 6.5v11c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2v-11l10 7.5L22 6.5z" fill="#4285F4" />
      <path d="M21.8 5.5L12 12.5 2.2 5.5C2.6 5.2 3.2 5 4 5h16c.8 0 1.4.2 1.8.5z" fill="#EA4335" />
      <path d="M2.2 5.5L12 12.5V5H4c-.8 0-1.4.2-1.8.5z" fill="#FBBC04" />
      <path d="M21.8 5.5L12 12.5V5h8c.8 0 1.4.2 1.8.5z" fill="#34A853" />
    </svg>
  )
}

export function SlackIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 127 127" fill="none" style={{ flexShrink: 0 }}>
      <path d="M27.2 80c0 7.3-5.9 13.2-13.2 13.2S.8 87.3.8 80s5.9-13.2 13.2-13.2h13.2V80zM33.7 80c0-7.3 5.9-13.2 13.2-13.2s13.2 5.9 13.2 13.2v33c0 7.3-5.9 13.2-13.2 13.2s-13.2-5.9-13.2-13.2V80z" fill="#E01E5A"/>
      <path d="M46.9 27.2c-7.3 0-13.2-5.9-13.2-13.2S39.6.8 46.9.8s13.2 5.9 13.2 13.2v13.2H46.9zM46.9 33.7c7.3 0 13.2 5.9 13.2 13.2s-5.9 13.2-13.2 13.2h-33C6.6 60.1.7 54.2.7 46.9s5.9-13.2 13.2-13.2h33z" fill="#36C5F0"/>
      <path d="M99.7 46.9c0-7.3 5.9-13.2 13.2-13.2s13.2 5.9 13.2 13.2-5.9 13.2-13.2 13.2H99.7V46.9zM93.2 46.9c0 7.3-5.9 13.2-13.2 13.2s-13.2-5.9-13.2-13.2v-33c0-7.3 5.9-13.2 13.2-13.2s13.2 5.9 13.2 13.2v33z" fill="#2EB67D"/>
      <path d="M80 99.7c7.3 0 13.2 5.9 13.2 13.2s-5.9 13.2-13.2 13.2-13.2-5.9-13.2-13.2V99.7H80zM80 93.2c-7.3 0-13.2-5.9-13.2-13.2s5.9-13.2 13.2-13.2h33c7.3 0 13.2 5.9 13.2 13.2s-5.9 13.2-13.2 13.2H80z" fill="#ECB22E"/>
    </svg>
  )
}

export function AIKnowledgeIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
      <circle cx="12" cy="12" r="11" fill="#A78BFA" opacity=".15"/>
      <path d="M12 4c-2.2 0-4 1.8-4 4v1.5c-1.2.5-2 1.7-2 3v1c0 1.3.7 2.5 2 3V18h8v-1.5c1.3-.5 2-1.7 2-3v-1c0-1.3-.8-2.5-2-3V8c0-2.2-1.8-4-4-4z" fill="#A78BFA" opacity=".3"/>
      <circle cx="9.5" cy="11" r="1.2" fill="#7C3AED"/>
      <circle cx="14.5" cy="11" r="1.2" fill="#7C3AED"/>
      <path d="M9 14.5c0 0 1.2 1.5 3 1.5s3-1.5 3-1.5" stroke="#7C3AED" strokeWidth="1.2" strokeLinecap="round" fill="none"/>
      <path d="M12 18v2M9 20.5h6" stroke="#7C3AED" strokeWidth="1.2" strokeLinecap="round"/>
    </svg>
  )
}

export function OneDriveIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" style={{ flexShrink: 0 }}>
      <path d="M28.6 18.4a9.6 9.6 0 0 1 9 6.3A7.2 7.2 0 0 1 40.8 38H24.6a7.2 7.2 0 0 1-1.8-14.2 9.6 9.6 0 0 1 5.8-5.4z" fill="#0078D4"/>
      <path d="M20.4 20.6a8.4 8.4 0 0 0-8.4 8.4c0 .3 0 .6.03.9A6 6 0 0 0 13.2 41h11.4a7.2 7.2 0 0 1-1.8-14.2 8.4 8.4 0 0 0-2.4-6.2z" fill="#0058A1"/>
      <path d="M28.6 18.4a9.6 9.6 0 0 0-8.2 2.2 8.4 8.4 0 0 1 2.4 6.2A7.2 7.2 0 0 1 24.6 38h16.2A7.2 7.2 0 0 0 37.6 24.7a9.6 9.6 0 0 0-9-6.3z" fill="#1490DF"/>
    </svg>
  )
}

export function SourceIcon({ type, size = 14 }) {
  switch (type) {
    case 'zoom':     return <ZoomIcon size={size} />
    case 'gdrive':   return <GDriveIcon size={size} />
    case 'gmail':    return <GmailIcon size={size} />
    case 'slack':    return <SlackIcon size={size} />
    case 'onedrive': return <OneDriveIcon size={size} />
    case 'ai':       return <AIKnowledgeIcon size={size} />
    default:         return <span style={{ fontSize: size - 2, lineHeight: 1 }}>—</span>
  }
}
