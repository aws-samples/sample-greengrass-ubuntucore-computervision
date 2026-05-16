/**
 * ConfidenceThresholdControl - Slider to set the inference confidence threshold via IoT Device Shadow
 */

import React, { useState, useEffect, useCallback } from 'react';
import { iotShadowService } from '../../services/iotShadowService';
import { useAuthenticatedAWS } from '../../hooks/useAuthenticatedAWS';
import './ConfidenceThresholdControl.css';

export interface ConfidenceThresholdControlProps {
  className?: string;
  thingName: string;
}

export const ConfidenceThresholdControl: React.FC<ConfidenceThresholdControlProps> = ({
  className = '',
  thingName,
}) => {
  const { credentials, region } = useAuthenticatedAWS();
  const [sliderValue, setSliderValue] = useState<number>(0.5);
  const [appliedValue, setAppliedValue] = useState<number | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'saving' | 'saved' | 'error'>('idle');
  const [errorMessage, setErrorMessage] = useState<string>('');

  // Load current threshold from shadow when thingName is set
  useEffect(() => {
    if (!thingName || !credentials) return;

    setStatus('loading');
    iotShadowService.getConfidenceThreshold(thingName, credentials, region)
      .then((value) => {
        if (value !== null) {
          setSliderValue(value);
          setAppliedValue(value);
        }
        setStatus('idle');
      })
      .catch((err) => {
        console.error('Failed to read confidence threshold from shadow:', err);
        setStatus('error');
        setErrorMessage('Failed to read current threshold from device shadow.');
      });
  }, [thingName, credentials, region]);

  const handleApply = useCallback(async () => {
    if (!thingName || !credentials) return;
    setStatus('saving');
    setErrorMessage('');
    try {
      await iotShadowService.setConfidenceThreshold(thingName, credentials, region, sliderValue);
      setAppliedValue(sliderValue);
      setStatus('saved');
      setTimeout(() => setStatus('idle'), 2000);
    } catch (err: any) {
      console.error('Failed to update confidence threshold:', err);
      setStatus('error');
      setErrorMessage(err?.message || 'Failed to update device shadow.');
    }
  }, [thingName, credentials, region, sliderValue]);

  const isDisabled = !thingName || !credentials || status === 'loading' || status === 'saving';
  const hasChanged = appliedValue === null || sliderValue !== appliedValue;

  return (
    <div className={`confidence-threshold ${className}`} role="group" aria-labelledby="confidence-threshold-label">
      <label id="confidence-threshold-label" className="confidence-threshold__label">
        Confidence Threshold
      </label>

      <div className="confidence-threshold__body">
        <div className="confidence-threshold__slider-row">
          <span className="confidence-threshold__bound">0.0</span>
          <input
            type="range"
            className="confidence-threshold__slider"
            min={0}
            max={1}
            step={0.05}
            value={sliderValue}
            onChange={(e) => setSliderValue(parseFloat(e.target.value))}
            disabled={isDisabled}
            aria-label="Confidence threshold slider"
            aria-valuemin={0}
            aria-valuemax={1}
            aria-valuenow={sliderValue}
          />
          <span className="confidence-threshold__bound">1.0</span>
          <span className="confidence-threshold__value">{sliderValue.toFixed(2)}</span>
        </div>

        <button
          type="button"
          className={`confidence-threshold__apply${hasChanged ? ' confidence-threshold__apply--changed' : ''}`}
          onClick={handleApply}
          disabled={isDisabled || !hasChanged}
          aria-label="Apply confidence threshold"
        >
          {status === 'saving' ? 'Applying...' : status === 'saved' ? 'Applied' : 'Apply'}
        </button>
      </div>

      {!thingName && (
        <p className="confidence-threshold__hint">Set an IoT Thing Name above to enable threshold control.</p>
      )}

      {status === 'error' && (
        <div className="confidence-threshold__error" role="alert">
          {errorMessage}
        </div>
      )}

      {appliedValue !== null && status !== 'error' && (
        <p className="confidence-threshold__applied">
          Device threshold: <strong>{appliedValue.toFixed(2)}</strong>
        </p>
      )}
    </div>
  );
};
