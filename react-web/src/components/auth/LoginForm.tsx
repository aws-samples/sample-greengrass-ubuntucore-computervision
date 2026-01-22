/**
 * Login Form Component with AWS branding and validation
 */

import React, { useState, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { AuthState } from '../../types/auth';
import { Button } from '../common/Button';
import './LoginForm.css';

export interface LoginFormProps {
  onSuccess?: () => void;
  className?: string;
}

export const LoginForm: React.FC<LoginFormProps> = ({
  onSuccess,
  className = '',
}) => {
  const { signIn, authState, error, clearError } = useAuth();

  // Form state
  const [formData, setFormData] = useState({
    username: '',
    password: '',
  });

  // Form validation state
  const [validationErrors, setValidationErrors] = useState<{
    username?: string;
    password?: string;
  }>({});

  // Form interaction state
  const [touched, setTouched] = useState<{
    username: boolean;
    password: boolean;
  }>({
    username: false,
    password: false,
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

  // Form validation
  const validateForm = () => {
    const errors: { username?: string; password?: string } = {};

    // Username validation
    if (!formData.username.trim()) {
      errors.username = 'Username is required';
    } else if (formData.username.length < 3) {
      errors.username = 'Username must be at least 3 characters';
    }

    // Password validation
    if (!formData.password) {
      errors.password = 'Password is required';
    } else if (formData.password.length < 6) {
      errors.password = 'Password must be at least 6 characters';
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
      username: true,
      password: true,
    });

    // Validate form
    if (!validateForm()) {
      return;
    }

    // Clear any existing errors
    clearError();

    // Attempt sign-in
    try {
      await signIn({
        username: formData.username.trim(),
        password: formData.password,
      });
    } catch (err) {
      // Error handling is managed by the AuthContext
      console.error('Login form submission error:', err);
    }
  };

  // Get field error message
  const getFieldError = (fieldName: 'username' | 'password') => {
    if (touched[fieldName] && validationErrors[fieldName]) {
      return validationErrors[fieldName];
    }
    return null;
  };

  // Check if field has error
  const hasFieldError = (fieldName: 'username' | 'password') => {
    return touched[fieldName] && !!validationErrors[fieldName];
  };

  return (
    <div className="login-form-container">
      <section className={`login-form ${className}`} aria-labelledby="login-title">
        {/* Header */}
        <header className="login-form__header">
          <h1 id="login-title" className="login-form__title">Sign In</h1>
        </header>

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="login-form__form" noValidate aria-label="Sign in form">
          {/* Username Field */}
          <div className="form-field">
            <label htmlFor="username" className="form-field__label">
              Username
            </label>
            <input
              type="text"
              id="username"
              name="username"
              value={formData.username}
              onChange={handleInputChange}
              onBlur={handleInputBlur}
              className={`form-field__input ${
                hasFieldError('username') ? 'form-field__input--error' : ''
              }`}
              placeholder="Enter your username"
              disabled={isLoading}
              autoComplete="username"
              aria-describedby={
                hasFieldError('username') ? 'username-error' : undefined
              }
              aria-invalid={hasFieldError('username')}
            />
            {getFieldError('username') && (
              <div id="username-error" className="form-field__error" role="alert">
                {getFieldError('username')}
              </div>
            )}
          </div>

          {/* Password Field */}
          <div className="form-field">
            <label htmlFor="password" className="form-field__label">
              Password
            </label>
            <input
              type="password"
              id="password"
              name="password"
              value={formData.password}
              onChange={handleInputChange}
              onBlur={handleInputBlur}
              className={`form-field__input ${
                hasFieldError('password') ? 'form-field__input--error' : ''
              }`}
              placeholder="Enter your password"
              disabled={isLoading}
              autoComplete="current-password"
              aria-describedby={
                hasFieldError('password') ? 'password-error' : undefined
              }
              aria-invalid={hasFieldError('password')}
            />
            {getFieldError('password') && (
              <div id="password-error" className="form-field__error" role="alert">
                {getFieldError('password')}
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

          {/* Submit Button */}
          <Button
            type="submit"
            variant="primary"
            size="lg"
            loading={isLoading}
            disabled={isLoading}
            className="login-form__submit"
          >
            {isLoading ? 'Signing In...' : 'Sign In'}
          </Button>
        </form>

        {/* Additional Information */}
        <footer className="login-form__footer">
          <p className="login-form__help-text">
            Having trouble signing in? Contact your administrator.
          </p>
        </footer>
      </section>

      {/* AWS Logo - Outside the form */}
      <div className="login-form__branding">
        <img
          src="https://d0.awsstatic.com/logos/powered-by-aws.png"
          alt="Powered by AWS"
          className="aws-logo login-form__logo-external"
        />
      </div>
    </div>
  );
};
