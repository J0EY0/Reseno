import { useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { useAuthSessionToken } from "@/hooks/use-auth-session-token";
import type { AppMessages } from "@/i18n";
import { notifyApiError } from "@/lib/api-error-notifier";
import { updateAuthUsername } from "@/lib/auth";
import { getAuthUsername } from "@/lib/auth-session";
import {
  validateUsernameUpdateForm,
  type UsernameUpdateFormErrors,
} from "@/lib/auth-validation";

export function useUsernameSettings(t: AppMessages) {
  const authToken = useAuthSessionToken();
  const username = authToken ? (getAuthUsername() ?? "") : "";
  const [usernameDraft, setUsernameDraft] = useState<string | null>(null);
  const newUsername = usernameDraft ?? username;
  const [currentPassword, setCurrentPassword] = useState("");
  const [formErrors, setFormErrors] = useState<UsernameUpdateFormErrors>({});
  const [isOpen, setIsOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const hasChanges = newUsername.trim() !== username;

  function changeOpen(open: boolean) {
    if (submittingRef.current) return;
    setIsOpen(open);
    setUsernameDraft(null);
    setCurrentPassword("");
    setFormErrors({});
  }

  function changeUsername(value: string) {
    setUsernameDraft(value);
    setFormErrors((current) => ({ ...current, newUsername: undefined }));
  }

  function changePassword(value: string) {
    setCurrentPassword(value);
    setFormErrors((current) => ({ ...current, currentPassword: undefined }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submittingRef.current || !hasChanges) return;

    const errors = validateUsernameUpdateForm(currentPassword, newUsername, t);
    setFormErrors(errors);
    if (Object.keys(errors).length > 0) return;

    submittingRef.current = true;
    setIsSubmitting(true);
    try {
      await updateAuthUsername({ currentPassword, newUsername });
      setIsOpen(false);
      setUsernameDraft(null);
      setCurrentPassword("");
      toast.success(t.usernameUpdated);
    } catch (error) {
      notifyApiError(error, t.usernameUpdateFailed);
    } finally {
      submittingRef.current = false;
      setIsSubmitting(false);
    }
  }

  return {
    newUsername,
    currentPassword,
    formErrors,
    isOpen,
    isSubmitting,
    hasChanges,
    changeOpen,
    changeUsername,
    changePassword,
    submit,
  };
}

export type UsernameSettingsController = ReturnType<typeof useUsernameSettings>;
