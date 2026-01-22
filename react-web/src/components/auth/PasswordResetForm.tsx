/**
 * Password Reset Form Component for Cognito NEW_PASSWORD_REQUIRED challenge
 */

import React, { useState, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { AuthState } from '../../types/auth';
import { Button } from '../common/Button';
import './LoginForm.css'; // Reuse login form styles

export interface PasswordResetFormProps {
  onSuccess?: () => void;
  onCancel?: () => void;
  className?: string;
}

interface PasswordStrength {
  score: number;
  feedback: string[];
  isValid: boolean;
}

export const PasswordResetForm: React.FC<PasswordResetFormProps> = ({
  onSuccess,
  onCancel,
  className = '',
}) => {
  const {
    completeNewPassword,
    authState,
    error,
    clearError,
    user,
    challengeSession,
  } = useAuth();

  // Form state
  const [formData, setFormData] = useState({
    newPassword: '',
    confirmPassword: '',
  });

  // Form validation state
  const [validationErrors, setValidationErrors] = useState<{
    newPassword?: string;
    confirmPassword?: string;
  }>({});

  // Form interaction state
  const [touched, setTouched] = useState<{
    newPassword: boolean;
    confirmPassword: boolean;
  }>({
    newPassword: false,
    confirmPassword: false,
  });

  // Password strength state
  const [passwordStrength, setPasswordStrength] = useState<PasswordStrength>({
    score: 0,
    feedback: [],
    isValid: false,
  });

  const isLoading = authState === AuthState.LOADING;
  const isAuthenticated = authState === AuthState.AUTHENTICATED;

  // Clear errors when form data changes
  useEffect(() => {
    if (error) {
      clearError();
    }
  }, [formData, error, clearError]);

  // Handle successful authentication
  useEffect(() => {
    if (isAuthenticated && onSuccess) {
      onSuccess();
    }
  }, [isAuthenticated, onSuccess]);

  // Password strength validation
  const validatePasswordStrength = (password: string): PasswordStrength => {
    const feedback: string[] = [];
    let score = 0;

    // Length check
    if (password.length >= 8) {
      score += 1;
    } else {
      feedback.push('Password must be at least 8 characters long');
    }

    // Uppercase check
    if (/[A-Z]/.test(password)) {
      score += 1;
    } else {
      feedback.push('Include at least one uppercase letter');
    }

    // Lowercase check
    if (/[a-z]/.test(password)) {
      score += 1;
    } else {
      feedback.push('Include at least one lowercase letter');
    }

    // Number check
    if (/\d/.test(password)) {
      score += 1;
    } else {
      feedback.push('Include at least one number');
    }

    // Special character check
    if (/[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?]/.test(password)) {
      score += 1;
    } else {
      feedback.push('Include at least one special character');
    }

    // Common patterns check
    if (
      password.toLowerCase().includes('password') ||
      password.toLowerCase().includes('123456') ||
      /(.)\1{2,}/.test(password)
    ) {
      feedback.push('Avoid common patterns and repeated characters');
      score = Math.max(0, score - 1);
    }

    return {
      score,
      feedback,
      isValid: score >= 4 && feedback.length <= 1, // Allow minor feedback
    };
  };

  // Update password strength when password changes
  useEffect(() => {
    if (formData.newPassword) {
      setPasswordStrength(validatePasswordStrength(formData.newPassword));
    } else {
      setPasswordStrength({ score: 0, feedback: [], isValid: false });
    }
  }, [formData.newPassword]);

  // Form validation
  const validateForm = () => {
    const errors: { newPassword?: string; confirmPassword?: string } = {};

    // New password validation
    if (!formData.newPassword) {
      errors.newPassword = 'New password is required';
    } else if (!passwordStrength.isValid) {
      errors.newPassword = 'Password does not meet security requirements';
    }

    // Confirm password validation
    if (!formData.confirmPassword) {
      errors.confirmPassword = 'Please confirm your password';
    } else if (formData.newPassword !== formData.confirmPassword) {
      errors.confirmPassword = 'Passwords do not match';
    }

    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  };

  // Handle input changes
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  // Handle input blur (mark as touched)
  const handleInputBlur = (e: React.FocusEvent<HTMLInputElement>) => {
    const { name } = e.target;
    setTouched((prev) => ({
      ...prev,
      [name]: true,
    }));
  };

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Mark all fields as touched
    setTouched({
      newPassword: true,
      confirmPassword: true,
    });

    // Validate form
    if (!validateForm()) {
      return;
    }

    // Clear any existing errors
    clearError();

    // Attempt password reset
    try {
      await completeNewPassword({
        newPassword: formData.newPassword,
        session: challengeSession || '', // Use the actual challenge session
      });
    } catch (err) {
      // Error handling is managed by the AuthContext
      console.error('Password reset form submission error:', err);
    }
  };

  // Handle cancel
  const handleCancel = () => {
    if (onCancel) {
      onCancel();
    }
  };

  // Get field error message
  const getFieldError = (fieldName: 'newPassword' | 'confirmPassword') => {
    if (touched[fieldName] && validationErrors[fieldName]) {
      return validationErrors[fieldName];
    }
    return null;
  };

  // Check if field has error
  const hasFieldError = (fieldName: 'newPassword' | 'confirmPassword') => {
    return touched[fieldName] && !!validationErrors[fieldName];
  };

  // Get password strength color
  const getPasswordStrengthColor = () => {
    if (passwordStrength.score <= 1) return 'var(--color-error)';
    if (passwordStrength.score <= 2) return 'var(--color-warning)';
    if (passwordStrength.score <= 3) return 'var(--color-info)';
    return 'var(--color-success)';
  };

  // Get password strength text
  const getPasswordStrengthText = () => {
    if (passwordStrength.score <= 1) return 'Weak';
    if (passwordStrength.score <= 2) return 'Fair';
    if (passwordStrength.score <= 3) return 'Good';
    return 'Strong';
  };

  return (
    <div className={`login-form ${className}`}>
      {/* Header */}
      <div className="login-form__header">
        <img
          src="https://d0.awsstatic.com/logos/powered-by-aws.png"
          alt="AWS Logo"
          className="aws-logo login-form__logo"
        />
        <h1 className="login-form__title">Set New Password</h1>
        <p className="login-form__subtitle">
          {user?.username && `Welcome, ${user.username}!`}
          <br />
          Please set a new password to continue.
        </p>
      </div>

      {/* Password Reset Form */}
      <form onSubmit={handleSubmit} className="login-form__form" noValidate>
        {/* New Password Field */}
        <div className="form-field">
          <label htmlFor="newPassword" className="form-field__label">
            New Password
          </label>
          <input
            type="password"
            id="newPassword"
            name="newPassword"
            value={formData.newPassword}
            onChange={handleInputChange}
            onBlur={handleInputBlur}
            className={`form-field__input ${
              hasFieldError('newPassword') ? 'form-field__input--error' : ''
            }`}
            placeholder="Enter your new password"
            disabled={isLoading}
            autoComplete="new-password"
            aria-describedby={
              hasFieldError('newPassword')
                ? 'newPassword-error'
                : 'password-strength'
            }
            aria-invalid={hasFieldError('newPassword')}
          />

          {/* Password Strength Indicator */}
          {formData.newPassword && (
            <div id="password-strength" className="password-strength">
              <div className="password-strength__bar">
                <div
                  className="password-strength__fill"
                  style={{
                    width: `${(passwordStrength.score / 5) * 100}%`,
                    backgroundColor: getPasswordStrengthColor(),
                  }}
                />
              </div>
              <div
                className="password-strength__text"
                style={{ color: getPasswordStrengthColor() }}
              >
                {getPasswordStrengthText()}
              </div>
            </div>
          )}

          {/* Password Requirements */}
          {touched.newPassword && passwordStrength.feedback.length > 0 && (
            <div className="password-requirements">
              <div className="password-requirements__title">
                Password Requirements:
              </div>
              <ul className="password-requirements__list">
                {passwordStrength.feedback.map((requirement, index) => (
                  <li key={index} className="password-requirements__item">
                    {requirement}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {getFieldError('newPassword') && (
            <div
              id="newPassword-error"
              className="form-field__error"
              role="alert"
            >
              {getFieldError('newPassword')}
            </div>
          )}
        </div>

        {/* Confirm Password Field */}
        <div className="form-field">
          <label htmlFor="confirmPassword" className="form-field__label">
            Confirm New Password
          </label>
          <input
            type="password"
            id="confirmPassword"
            name="confirmPassword"
            value={formData.confirmPassword}
            onChange={handleInputChange}
            onBlur={handleInputBlur}
            className={`form-field__input ${
              hasFieldError('confirmPassword') ? 'form-field__input--error' : ''
            }`}
            placeholder="Confirm your new password"
            disabled={isLoading}
            autoComplete="new-password"
            aria-describedby={
              hasFieldError('confirmPassword')
                ? 'confirmPassword-error'
                : undefined
            }
            aria-invalid={hasFieldError('confirmPassword')}
          />
          {getFieldError('confirmPassword') && (
            <div
              id="confirmPassword-error"
              className="form-field__error"
              role="alert"
            >
              {getFieldError('confirmPassword')}
            </div>
          )}
        </div>

        {/* Global Error Message */}
        {error && (
          <div className="form-error" role="alert">
            <div className="form-error__icon"></div>
            <div className="form-error__message">{error.message}</div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="form-actions">
          <Button
            type="submit"
            variant="primary"
            size="lg"
            loading={isLoading}
            disabled={isLoading || !passwordStrength.isValid}
            className="login-form__submit"
          >
            {isLoading ? 'Setting Password...' : 'Set New Password'}
          </Button>

          {onCancel && (
            <Button
              type="button"
              variant="secondary"
              size="lg"
              onClick={handleCancel}
              disabled={isLoading}
              className="form-cancel"
            >
              Cancel
            </Button>
          )}
        </div>
      </form>

      {/* Security Information */}
      <div className="login-form__footer">
        <p className="login-form__help-text">
           Your password is encrypted and stored securely.
        </p>
      </div>
    </div>
  );
};
