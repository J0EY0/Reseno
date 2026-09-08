import {
  PromptInput,
  PromptInputBody,
  PromptInputFooter,
  PromptInputTextarea,
  PromptInputTools,
} from '@/components/ai-elements/prompt-input'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { AppMessages } from '@/i18n'
import { canSubmitAgentPrompt } from '@/lib/agent-panel-state'
import { cn } from '@/lib/utils'
import type { ModelConfig } from '@/types/resume'
import { toast } from 'sonner'

import {
  IMAGE_ATTACHMENT_ACCEPT,
  MAX_AGENT_ATTACHMENT_BYTES,
  TEXT_ATTACHMENT_ACCEPT,
} from './copilot-attachment-policy'
import {
  AgentPromptAttachmentButton,
  AgentPromptAttachmentsDisplay,
  AgentPromptSubmitButton,
} from './copilot-attachments'
import type { AgentRequestPhase } from './agent-conversation-runtime'
import { CopilotModelSelector } from './copilot-model-selector'
import type { AgentPromptActions } from './use-agent-prompt-actions'

export function CopilotComposer({
  globalDropActive,
  hasConversationHistory,
  isSessionReady,
  modelConfigs,
  onOpenModelSettings,
  onSelectedModelConfigChange,
  promptActions,
  requestPhase,
  selectedModelConfig,
  selectedModelConfigId,
  t,
}: {
  globalDropActive: boolean
  hasConversationHistory: boolean
  isSessionReady: boolean
  modelConfigs: ModelConfig[]
  onOpenModelSettings: () => void
  onSelectedModelConfigChange: (modelConfigId: string) => void
  promptActions: AgentPromptActions
  requestPhase: AgentRequestPhase
  selectedModelConfig: ModelConfig | null
  selectedModelConfigId: string
  t: AppMessages
}) {
  const hasConfiguredModel = Boolean(selectedModelConfig)
  const isRequestBusy = requestPhase !== 'idle'
  const composerReady = canSubmitAgentPrompt({
    hasConfiguredModel,
    isRequestBusy,
    isSessionReady,
    isSubmitting: promptActions.isSubmittingPrompt,
  })
  const attachmentsReady =
    hasConfiguredModel &&
    isSessionReady &&
    !promptActions.isSubmittingPrompt

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className={cn(
            'rounded-[26px]',
            !hasConfiguredModel && 'cursor-not-allowed',
          )}
        >
          <PromptInput
            accept={
              selectedModelConfig?.supportsImage
                ? IMAGE_ATTACHMENT_ACCEPT
                : TEXT_ATTACHMENT_ACCEPT
            }
            className={cn(
              'p-0 text-foreground [&_[data-slot=input-group]]:overflow-hidden [&_[data-slot=input-group]]:rounded-[26px] [&_[data-slot=input-group]]:border-border/70 [&_[data-slot=input-group]]:bg-background [&_[data-slot=input-group]]:shadow-sm',
              !hasConfiguredModel &&
                '[&_[data-slot=input-group]]:cursor-not-allowed',
            )}
            globalDrop={globalDropActive && attachmentsReady}
            maxFiles={promptActions.promptAttachmentCapacity}
            maxFileSize={MAX_AGENT_ATTACHMENT_BYTES}
            multiple
            onError={() => {
              toast.error(t.agentAttachmentRejected, {
                closeButton: true,
              })
            }}
            onSubmit={promptActions.submitPrompt}
          >
            <AgentPromptAttachmentsDisplay
              disableRemoval={promptActions.isSubmittingPrompt}
              fallbackLabel={t.agentAttachmentFallback}
              removeLabel={t.agentRemoveAttachment}
              onLocalCountChange={promptActions.setPromptLocalAttachmentCount}
              onRemoveReferenced={
                promptActions.removeReferencedAttachment
              }
              referencedFiles={promptActions.referencedAttachments}
            />
            <PromptInputBody className="px-4 pt-3">
              <PromptInputTextarea
                aria-label={t.agentPromptPlaceholderShort}
                className="min-h-[58px] max-h-[132px] px-4 pb-0 pt-3 text-[15px] leading-[22px] text-foreground placeholder:text-muted-foreground disabled:cursor-not-allowed"
                disabled={!composerReady}
                placeholder={
                  hasConfiguredModel &&
                  isSessionReady &&
                  !hasConversationHistory
                    ? t.agentPromptPlaceholderShort
                    : ''
                }
                rows={1}
              />
            </PromptInputBody>

            <PromptInputFooter className="justify-between gap-2.5 px-4 pb-3.5 pt-1">
              <PromptInputTools className="min-w-0 gap-1.5">
                <AgentPromptAttachmentButton
                  disabled={
                    !attachmentsReady ||
                    promptActions.promptAttachmentCapacity === 0
                  }
                  label={t.agentAddAttachments}
                />
                <CopilotModelSelector
                  appliesToNextMessage={isRequestBusy}
                  disabled={promptActions.isSubmittingPrompt}
                  modelConfigs={modelConfigs}
                  onOpenModelSettings={onOpenModelSettings}
                  onSelectedModelConfigChange={onSelectedModelConfigChange}
                  selectedModelConfig={selectedModelConfig}
                  selectedModelConfigId={selectedModelConfigId}
                  t={t}
                />
              </PromptInputTools>

              <AgentPromptSubmitButton
                attachmentUploadProgress={
                  promptActions.attachmentUploadProgress
                }
                hasConfiguredModel={hasConfiguredModel}
                hasReferencedAttachments={
                  promptActions.referencedAttachments.length > 0
                }
                isSessionReady={isSessionReady}
                isSubmittingPrompt={promptActions.isSubmittingPrompt}
                onStop={promptActions.stopResponding}
                requestPhase={requestPhase}
                t={t}
              />
            </PromptInputFooter>
          </PromptInput>
        </div>
      </TooltipTrigger>
      {!hasConfiguredModel ? (
        <TooltipContent side="top">
          {t.agentPromptDisabledTooltip}
        </TooltipContent>
      ) : null}
    </Tooltip>
  )
}
