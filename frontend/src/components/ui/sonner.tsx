import { Toaster as Sonner, type ToasterProps } from 'sonner'

type AppToasterProps = ToasterProps & {
  theme?: 'light' | 'dark' | 'system'
}

export function Toaster({ theme = 'light', ...props }: AppToasterProps) {
  return (
    <Sonner
      theme={theme}
      richColors
      closeButton
      expand
      visibleToasts={4}
      className="toaster group"
      {...props}
    />
  )
}
