"use client";
/* eslint-disable react-refresh/only-export-components */

import type { FileUIPart } from "ai";
import { nanoid } from "nanoid";
import type { PropsWithChildren, RefObject } from "react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export interface PromptInputAttachments {
  files: (FileUIPart & { id: string })[];
  add: (files: File[] | FileList) => void;
  remove: (id: string) => void;
  clear: () => void;
  openFileDialog: () => void;
  fileInputRef: RefObject<HTMLInputElement | null>;
}

interface PromptInputController {
  textInput: {
    value: string;
    setInput: (value: string) => void;
    clear: () => void;
  };
  attachments: PromptInputAttachments;
  registerFileInput: (
    ref: RefObject<HTMLInputElement | null>,
    open: () => void,
  ) => void;
}

const PromptInputControllerContext =
  createContext<PromptInputController | null>(null);
const ProviderAttachmentsContext = createContext<PromptInputAttachments | null>(
  null,
);

export const LocalPromptInputAttachmentsContext =
  createContext<PromptInputAttachments | null>(null);

export function usePromptInputController() {
  const controller = useContext(PromptInputControllerContext);

  if (!controller) {
    throw new Error(
      "Wrap your component inside <PromptInputProvider> to use usePromptInputController().",
    );
  }

  return controller;
}

export function useOptionalPromptInputController() {
  return useContext(PromptInputControllerContext);
}

export function usePromptInputAttachments() {
  const provider = useContext(ProviderAttachmentsContext);
  const local = useContext(LocalPromptInputAttachmentsContext);
  const attachments = local ?? provider;

  if (!attachments) {
    throw new Error(
      "usePromptInputAttachments must be used within a PromptInput or PromptInputProvider",
    );
  }

  return attachments;
}

export function PromptInputProvider({
  initialInput = "",
  children,
}: PropsWithChildren<{ initialInput?: string }>) {
  const [textInput, setTextInput] = useState(initialInput);
  const [files, setFiles] = useState<(FileUIPart & { id: string })[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const openFileDialogRef = useRef<() => void>(() => {});
  const filesRef = useRef(files);

  useEffect(() => {
    filesRef.current = files;
  }, [files]);

  useEffect(
    () => () => {
      for (const file of filesRef.current) {
        if (file.url) {
          URL.revokeObjectURL(file.url);
        }
      }
    },
    [],
  );

  const add = useCallback((incomingFiles: File[] | FileList) => {
    const incoming = [...incomingFiles];

    if (incoming.length === 0) {
      return;
    }

    setFiles((current) => [
      ...current,
      ...incoming.map((file) => ({
        filename: file.name,
        id: nanoid(),
        mediaType: file.type,
        type: "file" as const,
        url: URL.createObjectURL(file),
      })),
    ]);
  }, []);

  const remove = useCallback((id: string) => {
    setFiles((current) => {
      const removed = current.find((file) => file.id === id);

      if (removed?.url) {
        URL.revokeObjectURL(removed.url);
      }

      return current.filter((file) => file.id !== id);
    });
  }, []);

  const clear = useCallback(() => {
    setFiles((current) => {
      for (const file of current) {
        if (file.url) {
          URL.revokeObjectURL(file.url);
        }
      }

      return [];
    });
  }, []);

  const openFileDialog = useCallback(() => {
    openFileDialogRef.current();
  }, []);

  const attachments = useMemo<PromptInputAttachments>(
    () => ({ add, clear, fileInputRef, files, openFileDialog, remove }),
    [add, clear, files, openFileDialog, remove],
  );
  const registerFileInput = useCallback(
    (ref: RefObject<HTMLInputElement | null>, open: () => void) => {
      fileInputRef.current = ref.current;
      openFileDialogRef.current = open;
    },
    [],
  );
  const controller = useMemo<PromptInputController>(
    () => ({
      attachments,
      registerFileInput,
      textInput: {
        clear: () => setTextInput(""),
        setInput: setTextInput,
        value: textInput,
      },
    }),
    [attachments, registerFileInput, textInput],
  );

  return (
    <PromptInputControllerContext.Provider value={controller}>
      <ProviderAttachmentsContext.Provider value={attachments}>
        {children}
      </ProviderAttachmentsContext.Provider>
    </PromptInputControllerContext.Provider>
  );
}
