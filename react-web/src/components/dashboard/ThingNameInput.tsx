/**
 * ThingNameInput Component - Text input to specify the IoT Thing name for shadow operations
 */

import React, { useState } from 'react';
import './ThingNameInput.css';

export interface ThingNameInputProps {
  className?: string;
  showLabel?: boolean;
  disabled?: boolean;
  onThingNameChange: (thingName: string) => void;
  thingName: string;
}

export const ThingNameInput: React.FC<ThingNameInputProps> = ({
  className = '',
  showLabel = true,
  disabled = false,
  onThingNameChange,
  thingName,
}) => {
  const [inputValue, setInputValue] = useState(thingName);

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(event.target.value);
  };

  const handleSet = () => {
    onThingNameChange(inputValue.trim());
  };

  const handleKeyPress = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      handleSet();
    }
  };

  const handleClear = () => {
    setInputValue('');
    onThingNameChange('');
  };

  const isSet = thingName.length > 0;

  return (
    <div className={`thing-name-input ${className}`} role="group" aria-labelledby="thing-name-label">
      {showLabel && (
        <label id="thing-name-label" htmlFor="thing-name-input" className="thing-name-input__label">
          IoT Thing Name
        </label>
      )}

      <div className="thing-name-input__wrapper">
        <input
          id="thing-name-input"
          type="text"
          className="thing-name-input__field"
          value={inputValue}
          onChange={handleInputChange}
          onKeyPress={handleKeyPress}
          placeholder="Enter IoT Thing name (e.g., MyGreengrassCore)"
          disabled={disabled}
          aria-label="IoT Thing name input"
        />

        <div className="thing-name-input__actions">
          {inputValue && (
            <button
              type="button"
              className="thing-name-input__clear"
              onClick={handleClear}
              disabled={disabled}
              aria-label="Clear Thing name"
              title="Clear Thing name"
            >
              ×
            </button>
          )}

          <button
            type="button"
            className="thing-name-input__set"
            onClick={handleSet}
            disabled={disabled || !inputValue.trim()}
            aria-label="Set IoT Thing name"
            title="Set Thing name"
          >
            {isSet && thingName === inputValue.trim() ? 'Set' : 'Set'}
          </button>
        </div>
      </div>

      {isSet && (
        <div className="thing-name-input__status" role="status" aria-live="polite">
          <span className="thing-name-input__status-text">Targeting: <strong>{thingName}</strong></span>
        </div>
      )}
    </div>
  );
};
