import { useLayoutEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, FieldError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import { getModelContextWindowReference } from "@/lib/model-config-api";

import { ModelFormFieldLabel } from "./model-config-field-labels";

type LookupStatus = "loading" | "found" | "not_found" | "ambiguous" | "failed";

export function ModelConfigContextWindowField({
  provider,
  model,
  value,
  error,
  messages,
  onChange,
}: {
  provider: string;
  model: string;
  value: string;
  error?: string;
  messages: AppMessages;
  onChange: (value: string) => void;
}) {
  const requestRef = useRef<AbortController | null>(null);
  const [feedback, setFeedback] = useState<{
    status: LookupStatus;
    value: string;
  } | null>(null);
  const status = feedback?.value === value ? feedback.status : null;
  const loading = status === "loading";
  const statusMessages: Record<LookupStatus, string> = {
    loading: messages.contextWindowCatalogLoading,
    found: messages.contextWindowCatalogFound,
    not_found: messages.contextWindowCatalogNotFound,
    ambiguous: messages.contextWindowCatalogAmbiguous,
    failed: messages.contextWindowCatalogFailed,
  };

  useLayoutEffect(
    () => () => {
      requestRef.current?.abort();
      requestRef.current = null;
    },
    [provider, model, value],
  );

  async function lookupContextWindow() {
    if (!model.trim() || requestRef.current) {
      return;
    }
    const request = new AbortController();
    requestRef.current = request;
    setFeedback({ status: "loading", value });
    try {
      const result = await getModelContextWindowReference(
        { provider, model: model.trim() },
        request.signal,
      );
      if (requestRef.current !== request || request.signal.aborted) {
        return;
      }
      if (result.status === "found") {
        if (
          result.contextWindowTokens === null ||
          !Number.isSafeInteger(result.contextWindowTokens) ||
          result.contextWindowTokens <= 0
        ) {
          throw new Error("Invalid catalog context window.");
        }
        const nextValue = String(result.contextWindowTokens);
        requestRef.current = null;
        onChange(nextValue);
        setFeedback({ status: "found", value: nextValue });
      } else {
        setFeedback({ status: result.status, value });
      }
    } catch {
      if (requestRef.current === request && !request.signal.aborted) {
        setFeedback({ status: "failed", value });
      }
    } finally {
      if (requestRef.current === request) {
        requestRef.current = null;
      }
    }
  }

  return (
    <Field
      orientation="horizontal"
      className="flex-wrap gap-x-3 gap-y-1.5"
      data-invalid={Boolean(error)}
    >
      <ModelFormFieldLabel
        htmlFor="model-context-window"
        label={messages.contextWindow}
        required
      />
      <div className="ml-auto flex max-w-full items-center gap-2">
        <Button
          id="model-context-catalog"
          type="button"
          variant="outline"
          size="xs"
          disabled={!model.trim() || loading}
          aria-busy={loading}
          onClick={() => void lookupContextWindow()}
        >
          {loading ? (
            <Spinner data-icon="inline-start" aria-hidden="true" />
          ) : null}
          {messages.contextWindowCatalog}
        </Button>
        <Input
          id="model-context-window"
          name="model-context-window"
          type="text"
          inputMode="numeric"
          autoComplete="off"
          value={value}
          placeholder={messages.placeholders.contextWindow}
          aria-invalid={Boolean(error)}
          className="w-32 min-w-0 shrink"
          aria-describedby={
            [
              error ? "model-context-window-error" : null,
              status ? "model-context-catalog-status" : null,
            ]
              .filter(Boolean)
              .join(" ") || undefined
          }
          onChange={(event) => {
            requestRef.current?.abort();
            requestRef.current = null;
            setFeedback(null);
            onChange(event.target.value);
          }}
        />
      </div>
      <FieldError id="model-context-window-error" className="basis-full">
        {error}
      </FieldError>
      {status ? (
        <p
          id="model-context-catalog-status"
          role="status"
          className="basis-full text-xs leading-relaxed text-muted-foreground"
        >
          {statusMessages[status]}
        </p>
      ) : null}
    </Field>
  );
}
