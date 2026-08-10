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
import { CopilotModelSelector } from './copilot-model-selector'
import type { AgentPromptActions } from './use-agent-prompt-actions'

export function CopilotComposer({
  globalDropActive,
  isResponding,
  isSessionReady,
  modelConfigs,
  onOpenModelSettings,
  onSelectedModelChange,
  promptActions,
  selectedModel,
  selectedModelId,
  t,
}: {
  globalDropActive: boolean
  isResponding: boolean
  isSessionReady: boolean
  modelConfigs: ModelConfig[]
  onOpenModelSettings: () => void
  onSelectedModelChange: (modelId: string) => void
  promptActions: AgentPromptActions
  selectedModel: ModelConfig | null
  selectedModelId: string
  t: AppMessages
}) {
  const hasConfiguredModel = Boolean(selectedModel)
  const composerReady = canSubmitAgentPrompt({
    hasConfiguredModel,
    isResponding,
    isSessionReady,
    isSubmitting: promptActions.isSubmittingPrompt,
  })

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
              selectedModel?.supportsImage
                ? IMAGE_ATTACHMENT_ACCEPT
                : TEXT_ATTACHMENT_ACCEPT
            }
            className={cn(
              'p-0 text-foreground [&_[data-slot=input-group]]:overflow-hidden [&_[data-slot=input-group]]:rounded-[26px] [&_[data-slot=input-group]]:border-border/70 [&_[data-slot=input-group]]:bg-background [&_[data-slot=input-group]]:shadow-sm',
              !hasConfiguredModel &&
                '[&_[data-slot=input-group]]:cursor-not-allowed',
            )}
            globalDrop={globalDropActive && composerReady}
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
                  hasConfiguredModel ? t.agentPromptPlaceholderShort : ''
                }
                rows={1}
              />
            </PromptInputBody>

            <PromptInputFooter className="justify-between gap-2.5 px-4 pb-3.5 pt-1">
              <PromptInputTools className="min-w-0 gap-1.5">
                <AgentPromptAttachmentButton
                  disabled={
                    !composerReady ||
                    promptActions.promptAttachmentCapacity === 0
                  }
                  label={t.agentAddAttachments}
                />
                <CopilotModelSelector
                  disabled={promptActions.isSubmittingPrompt}
                  modelConfigs={modelConfigs}
                  onOpenModelSettings={onOpenModelSettings}
                  onSelectedModelChange={onSelectedModelChange}
                  selectedModel={selectedModel}
                  selectedModelId={selectedModelId}
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
                isResponding={isResponding}
                isSessionReady={isSessionReady}
                isSubmittingPrompt={promptActions.isSubmittingPrompt}
                onStop={promptActions.stopResponding}
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
