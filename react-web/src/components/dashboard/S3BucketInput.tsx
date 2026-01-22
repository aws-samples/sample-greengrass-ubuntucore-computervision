/**
 * S3 Bucket Input Component - Simple text input for bucket name
 */

import React, { useState } from 'react';
import { useS3 } from '../../contexts/S3Context';
import './S3BucketInput.css';

export interface S3BucketInputProps {
  className?: string;
  showLabel?: boolean;
  disabled?: boolean;
}

export const S3BucketInput: React.FC<S3BucketInputProps> = ({
  className = '',
  showLabel = true,
  disabled = false,
}) => {
  const { state, actions } = useS3();
  const [inputValue, setInputValue] = useState(state.selectedBucket || '');

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(event.target.value);
  };

  const handleConnect = () => {
    if (inputValue.trim()) {
      actions.selectBucket(inputValue.trim());
    }
  };

  const handleKeyPress = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      handleConnect();
    }
  };

  const handleClear = () => {
    setInputValue('');
    actions.selectBucket('');
  };

  return (
    <div className={`s3-bucket-input ${className}`} role="group" aria-labelledby="s3-bucket-label">
      {showLabel && (
        <label id="s3-bucket-label" htmlFor="s3-bucket-input" className="s3-bucket-input__label">
          S3 Bucket Name
        </label>
      )}

      <div className="s3-bucket-input__wrapper">
        <input
          id="s3-bucket-input"
          type="text"
          className="s3-bucket-input__field"
          value={inputValue}
          onChange={handleInputChange}
          onKeyPress={handleKeyPress}
          placeholder="Enter S3 bucket name (e.g., my-bucket-name)"
          disabled={disabled || state.loading}
          aria-label="S3 bucket name input"
          aria-describedby={state.error ? "s3-error-message" : undefined}
          aria-invalid={!!state.error}
        />

        <div className="s3-bucket-input__actions">
          {inputValue && (
            <button
              type="button"
              className="s3-bucket-input__clear"
              onClick={handleClear}
              disabled={disabled || state.loading}
              aria-label="Clear S3 bucket name"
              title="Clear bucket name"
            >
              ×
            </button>
          )}

          <button
            type="button"
            className="s3-bucket-input__connect"
            onClick={handleConnect}
            disabled={disabled || state.loading || !inputValue.trim()}
            aria-label="Connect to S3 bucket"
            title="Connect to bucket"
          >
            {state.loading ? 'Connecting...' : 'Connect'}
          </button>
        </div>
      </div>

      {state.error && (
        <div id="s3-error-message" className="s3-bucket-input__error" role="alert" aria-live="assertive">
          <span className="s3-bucket-input__error-text">{state.error}</span>
        </div>
      )}
    </div>
  );
};
