import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import type { AppMessages } from '@/i18n'
import { downloadAgentAttachment } from '@/lib/agent-attachment-client'
import { isApiErrorToastShown } from '@/lib/api-client'
import type { AgentChatAttachment } from '@/types/api'

import type { AgentPanelMessage } from './copilot-message-model'
import type { SendAgentPrompt } from './copilot-panel-types'

export function useAgentMessageActions({
  isResponding,
  messages,
  resumeId,
  sessionResetVersion,
  sendPrompt,
  t,
}: {
  isResponding: boolean
  messages: AgentPanelMessage[]
  resumeId?: string
  sessionResetVersion: number
  sendPrompt: SendAgentPrompt
  t: AppMessages
}) {
  const actionScope = `${resumeId ?? ''}:${sessionResetVersion}`
  const [copiedState, setCopiedState] = useState<{
    messageId: string | null
    scope: string
  }>({ messageId: null, scope: actionScope })
  const [editingState, setEditingState] = useState<{
    messageId: string | null
    scope: string
    text: string
  }>({ messageId: null, scope: actionScope, text: '' })
  const copyTimerRef = useRef<number | null>(null)
  const copiedMessageId =
    copiedState.scope === actionScope ? copiedState.messageId : null
  const editingMessageId =
    editingState.scope === actionScope ? editingState.messageId : null
  const editingMessageText =
    editingState.scope === actionScope ? editingState.text : ''

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) {
        window.clearTimeout(copyTimerRef.current)
      }
    }
  }, [])

  const copyUserMessage = useCallback(
    async (message: AgentPanelMessage) => {
      try {
        await navigator.clipboard.writeText(message.text)
        setCopiedState({ messageId: message.id, scope: actionScope })

        if (copyTimerRef.current) {
          window.clearTimeout(copyTimerRef.current)
        }

        copyTimerRef.current = window.setTimeout(() => {
          setCopiedState((current) =>
            current.scope === actionScope && current.messageId === message.id
              ? { messageId: null, scope: actionScope }
              : current,
          )
          copyTimerRef.current = null
        }, 1200)
      } catch (error) {
        console.error('Failed to copy agent user message.', error)
      }
    },
    [actionScope],
  )

  const downloadHistoryAttachment = useCallback(
    async (file: AgentChatAttachment) => {
      if (!resumeId || !file.id) {
        return
      }

      try {
        const response = await downloadAgentAttachment(resumeId, file.id)
        const objectUrl = URL.createObjectURL(await response.blob())
        const link = document.createElement('a')
        link.href = objectUrl
        link.download = file.filename || t.agentAttachmentFallback
        link.hidden = true
        document.body.append(link)
        link.click()
        link.remove()
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
      } catch (error) {
        console.error('Failed to download Agent attachment.', error)
        if (!isApiErrorToastShown(error)) {
          toast.error(t.agentAttachmentDownloadFailed, {
            closeButton: true,
          })
        }
      }
    },
    [resumeId, t.agentAttachmentDownloadFailed, t.agentAttachmentFallback],
  )

  const startEditingUserMessage = useCallback(
    (message: AgentPanelMessage) => {
      if (isResponding) {
        return
      }

      setEditingState({
        messageId: message.id,
        scope: actionScope,
        text: message.text,
      })
    },
    [actionScope, isResponding],
  )

  const cancelEditingUserMessage = useCallback(() => {
    setEditingState({ messageId: null, scope: actionScope, text: '' })
  }, [actionScope])

  const setEditingMessageText = useCallback(
    (text: string) => {
      setEditingState((current) => ({
        messageId:
          current.scope === actionScope ? current.messageId : null,
        scope: actionScope,
        text,
      }))
    },
    [actionScope],
  )

  const submitEditedUserMessage = useCallback(
    async (message: AgentPanelMessage) => {
      const nextText = editingMessageText.trim()

      if (!nextText) {
        toast.info(t.agentEditEmpty, {
          closeButton: true,
        })
        return
      }

      const messageIndex = messages.findIndex((item) => item.id === message.id)
      if (messageIndex < 0 || isResponding) {
        return
      }

      cancelEditingUserMessage()
      await sendPrompt(nextText, message.files ?? [], {
        baseMessages: messages.slice(0, messageIndex),
        messageId: message.id,
        replaceSessionBeforeSend: true,
      })
    },
    [
      cancelEditingUserMessage,
      editingMessageText,
      isResponding,
      messages,
      sendPrompt,
      t.agentEditEmpty,
    ],
  )

  const retryUserMessage = useCallback(
    async (message: AgentPanelMessage) => {
      const messageIndex = messages.findIndex((item) => item.id === message.id)
      if (messageIndex < 0 || isResponding) {
        return
      }

      await sendPrompt(message.text, message.files ?? [], {
        baseMessages: messages.slice(0, messageIndex),
        messageId: message.id,
      })
    },
    [isResponding, messages, sendPrompt],
  )

  return {
    cancelEditingUserMessage,
    copiedMessageId,
    copyUserMessage,
    downloadHistoryAttachment,
    editingMessageId,
    editingMessageText,
    retryUserMessage,
    setEditingMessageText,
    startEditingUserMessage,
    submitEditedUserMessage,
  }
}

export type AgentMessageActions = ReturnType<typeof useAgentMessageActions>
