/**
 * MQTT Topic Input Component - Simple text input for MQTT topic
 */

import React, { useState, useEffect } from 'react';
import { useMqtt } from '../../contexts/MqttContext';
import './MqttTopicInput.css';

export interface MqttTopicInputProps {
  className?: string;
  showLabel?: boolean;
  disabled?: boolean;
  onTopicChange?: (topic: string) => void;
}

export const MqttTopicInput: React.FC<MqttTopicInputProps> = ({
  className = '',
  showLabel = true,
  disabled = false,
  onTopicChange,
}) => {
  const { state, actions } = useMqtt();
  const [inputValue, setInputValue] = useState('');
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(event.target.value);
  };

  const handleConnect = async () => {
    if (inputValue.trim()) {
      try {
        console.log(` Connecting to MQTT topic: ${inputValue.trim()}`);
        await actions.connect(inputValue.trim());
        setSelectedTopic(inputValue.trim());

        if (onTopicChange) {
          onTopicChange(inputValue.trim());
        }
      } catch (error) {
        console.error('Failed to connect to MQTT topic:', error);
      }
    }
  };

  const handleKeyPress = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      handleConnect();
    }
  };

  const handleClear = () => {
    setInputValue('');
    setSelectedTopic(null);
    actions.disconnect();

    if (onTopicChange) {
      onTopicChange('');
    }
  };

  // Update selected topic when MQTT state changes
  useEffect(() => {
    if (state.connected && !selectedTopic) {
      setSelectedTopic(inputValue);
    } else if (!state.connected && selectedTopic) {
      setSelectedTopic(null);
    }
  }, [state.connected, selectedTopic, inputValue]);

  return (
    <div className={`mqtt-topic-input ${className}`} role="group" aria-labelledby="mqtt-topic-label">
      {showLabel && (
        <label id="mqtt-topic-label" htmlFor="mqtt-topic-input" className="mqtt-topic-input__label">
          MQTT Topic
        </label>
      )}

      <div className="mqtt-topic-input__wrapper">
        <input
          id="mqtt-topic-input"
          type="text"
          className="mqtt-topic-input__field"
          value={inputValue}
          onChange={handleInputChange}
          onKeyPress={handleKeyPress}
          placeholder="Enter MQTT topic (e.g., dashboard/messages)"
          disabled={disabled || state.connectionStatus === 'connecting'}
          aria-label="MQTT topic input"
          aria-describedby={state.error ? "mqtt-error-message" : undefined}
          aria-invalid={!!state.error}
        />

        <div className="mqtt-topic-input__actions">
          {inputValue && (
            <button
              type="button"
              className="mqtt-topic-input__clear"
              onClick={handleClear}
              disabled={disabled || state.connectionStatus === 'connecting'}
              aria-label="Clear MQTT topic"
              title="Clear topic"
            >
              ×
            </button>
          )}

          <button
            type="button"
            className="mqtt-topic-input__connect"
            onClick={handleConnect}
            disabled={disabled || state.connectionStatus === 'connecting' || !inputValue.trim()}
            aria-label="Subscribe to MQTT topic"
            title="Subscribe to topic"
          >
            {state.connectionStatus === 'connecting' ? 'Connecting...' : 'Subscribe'}
          </button>
        </div>
      </div>

      {state.error && (
        <div id="mqtt-error-message" className="mqtt-topic-input__error" role="alert" aria-live="assertive">
          <span className="mqtt-topic-input__error-text">{state.error}</span>
        </div>
      )}
    </div>
  );
};
