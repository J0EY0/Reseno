import type { FileUIPart } from "ai";
import { nanoid } from "nanoid";
import type {
  ChangeEventHandler,
  FormEvent,
  FormEventHandler,
} from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  useOptionalPromptInputController,
  type PromptInputAttachments,
} from "@/components/ai-elements/prompt-input-context";

export interface PromptInputMessage {
  text: string;
  files: FileUIPart[];
}

export interface PromptInputFileError {
  code: "accept" | "max_file_size" | "max_files";
  message: string;
}

interface UsePromptInputFormOptions {
  accept?: string;
  globalDrop?: boolean;
  maxFiles?: number;
  maxFileSize?: number;
  syncHiddenInput?: boolean;
  onError?: (error: PromptInputFileError) => void;
  onSubmit: (
    message: PromptInputMessage,
    event: FormEvent<HTMLFormElement>,
  ) => void | Promise<void>;
}

function matchesAcceptedType(file: File, accept?: string) {
  if (!accept?.trim()) {
    return true;
  }

  return accept
    .split(",")
    .map((pattern) => pattern.trim())
    .filter(Boolean)
    .some((pattern) =>
      pattern.endsWith("/*")
        ? file.type.startsWith(pattern.slice(0, -1))
        : file.type === pattern,
    );
}

function selectValidFiles(
  fileList: File[] | FileList,
  {
    accept,
    currentCount,
    maxFiles,
    maxFileSize,
    onError,
  }: Pick<
    UsePromptInputFormOptions,
    "accept" | "maxFiles" | "maxFileSize" | "onError"
  > & { currentCount: number },
) {
  const incoming = [...fileList];
  const accepted = incoming.filter((file) =>
    matchesAcceptedType(file, accept),
  );

  if (incoming.length > 0 && accepted.length === 0) {
    onError?.({
      code: "accept",
      message: "No files match the accepted types.",
    });
    return [];
  }

  const sized = accepted.filter((file) =>
    maxFileSize ? file.size <= maxFileSize : true,
  );

  if (accepted.length > 0 && sized.length === 0) {
    onError?.({
      code: "max_file_size",
      message: "All files exceed the maximum size.",
    });
    return [];
  }

  const capacity =
    typeof maxFiles === "number"
      ? Math.max(0, maxFiles - currentCount)
      : undefined;
  const selected =
    typeof capacity === "number" ? sized.slice(0, capacity) : sized;

  if (typeof capacity === "number" && sized.length > capacity) {
    onError?.({
      code: "max_files",
      message: "Too many files. Some were not added.",
    });
  }

  return selected;
}

async function convertBlobUrlToDataUrl(url: string) {
  try {
    const response = await fetch(url);
    const blob = await response.blob();

    return await new Promise<string | null>((resolve) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result as string);
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    });
  } catch {
    return null;
  }
}

export function usePromptInputForm({
  accept,
  globalDrop,
  maxFiles,
  maxFileSize,
  syncHiddenInput,
  onError,
  onSubmit,
}: UsePromptInputFormOptions) {
  const controller = useOptionalPromptInputController();
  const usingProvider = controller !== null;
  const inputRef = useRef<HTMLInputElement | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);
  const submissionInFlightRef = useRef(false);
  const [localFiles, setLocalFiles] = useState<
    (FileUIPart & { id: string })[]
  >([]);
  const files = controller?.attachments.files ?? localFiles;
  const filesRef = useRef(files);

  useEffect(() => {
    filesRef.current = files;
  }, [files]);

  const addLocal = useCallback(
    (fileList: File[] | FileList) => {
      setLocalFiles((current) => {
        const selected = selectValidFiles(fileList, {
          accept,
          currentCount: current.length,
          maxFiles,
          maxFileSize,
          onError,
        });
        const additions = selected.map((file) => ({
          filename: file.name,
          id: nanoid(),
          mediaType: file.type,
          type: "file" as const,
          url: URL.createObjectURL(file),
        }));

        return [...current, ...additions];
      });
    },
    [accept, maxFiles, maxFileSize, onError],
  );

  const addWithProviderValidation = useCallback(
    (fileList: File[] | FileList) => {
      const selected = selectValidFiles(fileList, {
        accept,
        currentCount: files.length,
        maxFiles,
        maxFileSize,
        onError,
      });

      if (selected.length > 0) {
        controller?.attachments.add(selected);
      }
    },
    [accept, controller, files.length, maxFiles, maxFileSize, onError],
  );

  const removeLocal = useCallback((id: string) => {
    setLocalFiles((current) => {
      const removed = current.find((file) => file.id === id);

      if (removed?.url) {
        URL.revokeObjectURL(removed.url);
      }

      return current.filter((file) => file.id !== id);
    });
  }, []);

  const clearLocal = useCallback(() => {
    setLocalFiles((current) => {
      for (const file of current) {
        if (file.url) {
          URL.revokeObjectURL(file.url);
        }
      }

      return [];
    });
  }, []);
  const openLocalFileDialog = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const add = usingProvider ? addWithProviderValidation : addLocal;
  const clear = usingProvider ? controller.attachments.clear : clearLocal;
  const remove = usingProvider ? controller.attachments.remove : removeLocal;
  const openFileDialog = usingProvider
    ? controller.attachments.openFileDialog
    : openLocalFileDialog;

  useEffect(() => {
    if (controller) {
      controller.registerFileInput(inputRef, () => inputRef.current?.click());
    }
  }, [controller]);

  useEffect(() => {
    if (syncHiddenInput && inputRef.current && files.length === 0) {
      inputRef.current.value = "";
    }
  }, [files.length, syncHiddenInput]);

  useEffect(() => {
    const target = globalDrop ? document : formRef.current;

    if (!target) {
      return;
    }

    const handleDragOver = (event: Event) => {
      const dragEvent = event as DragEvent;

      if (dragEvent.dataTransfer?.types?.includes("Files")) {
        dragEvent.preventDefault();
      }
    };
    const handleDrop = (event: Event) => {
      const dragEvent = event as DragEvent;

      if (dragEvent.dataTransfer?.types?.includes("Files")) {
        dragEvent.preventDefault();
      }
      if (dragEvent.dataTransfer?.files?.length) {
        add(dragEvent.dataTransfer.files);
      }
    };

    target.addEventListener("dragover", handleDragOver);
    target.addEventListener("drop", handleDrop);

    return () => {
      target.removeEventListener("dragover", handleDragOver);
      target.removeEventListener("drop", handleDrop);
    };
  }, [add, globalDrop]);

  useEffect(
    () => () => {
      if (!usingProvider) {
        for (const file of filesRef.current) {
          if (file.url) {
            URL.revokeObjectURL(file.url);
          }
        }
      }
    },
    [usingProvider],
  );

  const handleFileChange: ChangeEventHandler<HTMLInputElement> = useCallback(
    (event) => {
      if (event.currentTarget.files) {
        add(event.currentTarget.files);
      }
      event.currentTarget.value = "";
    },
    [add],
  );

  const attachments = useMemo<PromptInputAttachments>(
    () => ({
      add,
      clear,
      fileInputRef: inputRef,
      files: files.map((file) => ({ ...file })),
      openFileDialog,
      remove,
    }),
    [add, clear, files, openFileDialog, remove],
  );

  const handleSubmit: FormEventHandler<HTMLFormElement> = useCallback(
    async (event) => {
      event.preventDefault();

      if (submissionInFlightRef.current) {
        return;
      }
      submissionInFlightRef.current = true;

      const form = event.currentTarget;
      const text = controller
        ? controller.textInput.value
        : String(new FormData(form).get("message") ?? "");

      if (!controller) {
        form.reset();
      }

      try {
        const convertedFiles: FileUIPart[] = await Promise.all(
          files.map(async ({ id: localId, ...file }) => {
            // Browser-local attachment ids must not enter the chat payload.
            void localId;

            if (!file.url?.startsWith("blob:")) {
              return file;
            }

            const dataUrl = await convertBlobUrlToDataUrl(file.url);
            return { ...file, url: dataUrl ?? file.url };
          }),
        );
        const result = onSubmit({ files: convertedFiles, text }, event);

        if (result instanceof Promise) {
          await result;
        }

        clear();
        controller?.textInput.clear();
      } catch {
        // Keep the captured input and attachments available for retry.
      } finally {
        submissionInFlightRef.current = false;
      }
    },
    [clear, controller, files, onSubmit],
  );

  return {
    attachments,
    formRef,
    handleFileChange,
    handleSubmit,
    inputRef,
  };
}
