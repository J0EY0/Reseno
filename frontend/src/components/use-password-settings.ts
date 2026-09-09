import { useState, type FormEvent } from "react";

import type { AppMessages } from "@/i18n";
import { updateAuthPassword } from "@/lib/auth";
import {
  validatePasswordUpdateForm,
  type PasswordUpdateFormErrors,
} from "@/lib/auth-validation";

export function usePasswordSettings({
  t,
  onPasswordChanged,
}: {
  t: AppMessages;
  onPasswordChanged: () => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [formErrors, setFormErrors] = useState<PasswordUpdateFormErrors>({});
  const [requestError, setRequestError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isOpen, setIsOpen] = useState(false);

  function resetForm() {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setFormErrors({});
    setRequestError(null);
  }

  function changeOpen(open: boolean) {
    setIsOpen(open);
    if (!open) {
      resetForm();
    }
  }

  function changeCurrentPassword(value: string) {
    setCurrentPassword(value);
    setFormErrors((current) => ({
      ...current,
      currentPassword: undefined,
    }));
  }

  function changeNewPassword(value: string) {
    setNewPassword(value);
    setFormErrors((current) => ({
      ...current,
      newPassword: undefined,
      confirmPassword: undefined,
    }));
  }

  function changeConfirmPassword(value: string) {
    setConfirmPassword(value);
    setFormErrors((current) => ({
      ...current,
      confirmPassword: undefined,
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRequestError(null);
    const nextErrors = validatePasswordUpdateForm(
      currentPassword,
      newPassword,
      confirmPassword,
      t,
    );

    if (Object.keys(nextErrors).length > 0) {
      setFormErrors(nextErrors);
      return;
    }

    setFormErrors({});
    setIsSubmitting(true);

    try {
      await updateAuthPassword({
        currentPassword,
        newPassword,
        confirmPassword,
      });
      setIsOpen(false);
      resetForm();
      onPasswordChanged();
    } catch (error) {
      setRequestError(
        error instanceof Error ? error.message : t.passwordUpdateFailed,
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return {
    currentPassword,
    newPassword,
    confirmPassword,
    formErrors,
    requestError,
    isSubmitting,
    isOpen,
    changeOpen,
    changeCurrentPassword,
    changeNewPassword,
    changeConfirmPassword,
    submit,
  };
}

export type PasswordSettingsController = ReturnType<typeof usePasswordSettings>;
