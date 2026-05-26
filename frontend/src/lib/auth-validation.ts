import type { AppMessages } from "@/i18n";

export type LoginFormErrors = {
  username?: string;
  password?: string;
};

export type PasswordUpdateFormErrors = {
  currentPassword?: string;
  newPassword?: string;
  confirmPassword?: string;
};

const usernamePattern = /^[A-Za-z0-9_-]+$/;
const hasPasswordLetter = /[A-Za-z]/;
const hasPasswordNumber = /\d/;

export function validateLoginPassword(password: string, t: AppMessages) {
  if (!password) {
    return t.loginPasswordRequired;
  }

  if (password.length < 8) {
    return t.loginPasswordTooShort;
  }

  if (!hasPasswordLetter.test(password) || !hasPasswordNumber.test(password)) {
    return t.loginPasswordInvalid;
  }

  return undefined;
}

export function validateLoginForm(
  username: string,
  password: string,
  t: AppMessages,
) {
  const errors: LoginFormErrors = {};
  const trimmedUsername = username.trim();

  if (!trimmedUsername) {
    errors.username = t.loginUsernameRequired;
  } else if (trimmedUsername.length < 3) {
    errors.username = t.loginUsernameTooShort;
  } else if (!usernamePattern.test(trimmedUsername)) {
    errors.username = t.loginUsernameInvalid;
  }

  const passwordError = validateLoginPassword(password, t);
  if (passwordError) {
    errors.password = passwordError;
  }

  return errors;
}

export function validatePasswordUpdateForm(
  currentPassword: string,
  newPassword: string,
  confirmPassword: string,
  t: AppMessages,
) {
  const errors: PasswordUpdateFormErrors = {};

  const currentPasswordError = validateLoginPassword(currentPassword, t);
  if (currentPasswordError) {
    errors.currentPassword = currentPasswordError;
  }

  const newPasswordError = validateLoginPassword(newPassword, t);
  if (newPasswordError) {
    errors.newPassword = newPasswordError;
  }

  if (!confirmPassword) {
    errors.confirmPassword = t.confirmPasswordRequired;
  } else if (newPassword && confirmPassword !== newPassword) {
    errors.confirmPassword = t.apiMessages.PASSWORD_CONFIRMATION_MISMATCH;
  }

  return errors;
}
