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

export type SetupFormErrors = {
  username?: string;
  password?: string;
  confirmPassword?: string;
};

const usernamePattern = /^[A-Za-z0-9_-]+$/;
const hasPasswordLetter = /[A-Za-z]/;
const hasPasswordNumber = /\d/;

function validateRequiredPassword(password: string, t: AppMessages) {
  if (!password) {
    return t.loginPasswordRequired;
  }

  return undefined;
}

export function validateNewPassword(password: string, t: AppMessages) {
  const requiredError = validateRequiredPassword(password, t);
  if (requiredError) {
    return requiredError;
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
  }

  const passwordError = validateRequiredPassword(password, t);
  if (passwordError) {
    errors.password = passwordError;
  }

  return errors;
}

export function validateSetupForm(
  username: string,
  password: string,
  confirmPassword: string,
  t: AppMessages,
) {
  const errors: SetupFormErrors = {};
  const trimmedUsername = username.trim();

  if (!trimmedUsername) {
    errors.username = t.loginUsernameRequired;
  } else if (trimmedUsername.length < 3) {
    errors.username = t.loginUsernameTooShort;
  } else if (!usernamePattern.test(trimmedUsername)) {
    errors.username = t.loginUsernameInvalid;
  }

  const passwordError = validateNewPassword(password, t);
  if (passwordError) {
    errors.password = passwordError;
  }

  if (!confirmPassword) {
    errors.confirmPassword = t.setupConfirmPasswordRequired;
  } else if (password && confirmPassword !== password) {
    errors.confirmPassword = t.apiMessages.PASSWORD_CONFIRMATION_MISMATCH;
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

  const currentPasswordError = validateRequiredPassword(currentPassword, t);
  if (currentPasswordError) {
    errors.currentPassword = currentPasswordError;
  }

  const newPasswordError = validateNewPassword(newPassword, t);
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
