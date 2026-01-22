/**
 * Message Feed Component - Displays real-time MQTT messages
 */

import React, { useCallback, useRef, useEffect } from 'react';
import { useMqtt } from '../../contexts/MqttContext';
import { MqttMessage, ConnectionStatus } from '../../types/mqtt';
import './MessageFeed.css';

export interface MessageFeedProps {
  className?: string;
  maxMessages?: number;
  showConnectionStatus?: boolean;
  onMessageClick?: (message: MqttMessage) => void;
}

export const MessageFeed: React.FC<MessageFeedProps> = ({
  className = '',
  maxMessages = 100,
  showConnectionStatus = true,
  onMessageClick,
}) => {
  const { state, actions } = useMqtt();
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = React.useState(false);

  /**
   * Scroll to top of messages (where latest messages appear)
   */
  const scrollToTop = useCallback(() => {
    if (containerRef.current) {
      containerRef.current.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, []);

  /**
   * Handle message click
   */
  const handleMessageClick = useCallback(
    (message: MqttMessage) => {
      if (onMessageClick) {
        onMessageClick(message);
      }
    },
    [onMessageClick]
  );

  /**
   * Handle manual refresh/reconnect
   */
  const handleRefresh = useCallback(() => {
    // Just clear error - reconnection should be handled by MqttTopicInput
    actions.clearError();
  }, [actions]);

  /**
   * Handle clear messages
   */
  const handleClearMessages = useCallback(() => {
    actions.clearMessages();
  }, [actions]);

  /**
   * Format timestamp
   */
  const formatTimestamp = (date: Date): string => {
    return new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(date);
  };

  /**
   * Format message payload for display
   */
  const formatPayload = (payload: string): string => {
    try {
      // Try to parse as JSON for pretty formatting
      const parsed = JSON.parse(payload);
      return JSON.stringify(parsed, null, 2);
    } catch {
      // Return as-is if not JSON
      return payload;
    }
  };

  /**
   * Get connection status display info
   */
  const getConnectionStatusInfo = () => {
    switch (state.connectionStatus) {
      case ConnectionStatus.CONNECTED:
        return { icon: null, text: 'Connected', className: 'connected' };
      case ConnectionStatus.CONNECTING:
        return { icon: null, text: 'Connecting...', className: 'connecting' };
      case ConnectionStatus.RECONNECTING:
        return {
          icon: null,
          text: 'Reconnecting...',
          className: 'reconnecting',
        };
      case ConnectionStatus.ERROR:
        return { icon: null, text: 'Error', className: 'error' };
      case ConnectionStatus.DISCONNECTED:
      default:
        return { icon: null, text: 'Disconnected', className: 'disconnected' };
    }
  };

  /**
   * Check if user is near top of scroll area (where new messages appear)
   */
  const isNearTop = useCallback(() => {
    if (!containerRef.current) return true;
    const { scrollTop } = containerRef.current;
    return scrollTop < 50; // Within 50px of top
  }, []);

  /**
   * Handle scroll events to show/hide scroll button
   */
  const handleScroll = useCallback(() => {
    if (!containerRef.current) return;
    
    const nearTop = isNearTop();
    setShowScrollButton(!nearTop && state.messages.length > 0);
  }, [isNearTop, state.messages.length]);

  /**
   * Handle scroll to top button click
   */
  const handleScrollToTop = useCallback(() => {
    scrollToTop();
  }, [scrollToTop]);

  /**
   * Set up scroll event listener
   */
  useEffect(() => {
    const container = containerRef.current;
    if (container) {
      container.addEventListener('scroll', handleScroll, { passive: true });
      return () => {
        container.removeEventListener('scroll', handleScroll);
      };
    }
  }, [handleScroll]);

  const statusInfo = getConnectionStatusInfo();

  return (
    <div className={`message-feed ${className}`} role="region" aria-labelledby="message-feed-title">
      {/* Header */}
      <div className="message-feed__header">
        <div className="message-feed__info">
          <h3 id="message-feed-title" className="message-feed__title">
            IoT Message Feed ({state.messageCount})
          </h3>
          {showConnectionStatus && (
            <div
              className={`message-feed__status message-feed__status--${statusInfo.className}`}
              role="status"
              aria-live="polite"
              aria-label={`MQTT connection status: ${statusInfo.text}`}
            >
              <span className="message-feed__status-indicator" aria-hidden="true"></span>
              <span className="message-feed__status-text">
                {statusInfo.text}
              </span>
            </div>
          )}
        </div>
        <div className="message-feed__actions">
          <button
            className="message-feed__clear"
            onClick={handleClearMessages}
            disabled={state.messages.length === 0}
            aria-label="Clear all messages"
            title="Clear all messages"
          >
            Clear
          </button>
          <button
            className="message-feed__refresh"
            onClick={handleRefresh}
            disabled={
              state.connectionStatus === ConnectionStatus.CONNECTING ||
              state.connectionStatus === ConnectionStatus.RECONNECTING
            }
            aria-label="Refresh MQTT connection"
            title="Refresh connection"
          >
            {state.connectionStatus === ConnectionStatus.CONNECTING
              ? 'Connecting'
              : state.connectionStatus === ConnectionStatus.RECONNECTING
                ? 'Reconnecting'
                : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Error banner */}
      {state.error && (
        <div className="message-feed__error-banner" role="alert" aria-live="assertive">
          <span className="message-feed__error-banner-text">
            {state.error}
          </span>
          <button
            className="message-feed__error-banner-close"
            onClick={actions.clearError}
            aria-label="Dismiss error message"
            title="Dismiss error"
          >
            ×
          </button>
        </div>
      )}

      {/* Messages container */}
      <div className="message-feed__container" ref={containerRef} role="log" aria-live="polite" aria-atomic="false">
        {state.messages.length === 0 ? (
          <div className="message-feed__empty">
            <svg className="message-feed__empty-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            <h4 className="message-feed__empty-title">
              {state.connectionStatus === ConnectionStatus.CONNECTED
                ? 'Waiting for Messages'
                : 'Not Connected'}
            </h4>
            <p className="message-feed__empty-text">
              {state.connectionStatus === ConnectionStatus.CONNECTED
                ? 'Real-time IoT messages will appear here when received'
                : 'Connect to start receiving real-time IoT messages'}
            </p>
          </div>
        ) : (
          <div className="message-feed__messages">
            {state.messages.slice(0, maxMessages).map((message, index) => (
              <div
                key={`${message.timestamp.getTime()}-${index}`}
                className="message-feed__message"
                onClick={() => handleMessageClick(message)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleMessageClick(message);
                  }
                }}
                aria-label={`Message from ${message.topic} at ${formatTimestamp(message.timestamp)}`}
              >
                <div className="message-feed__message-header">
                  <span className="message-feed__message-topic">
                    {message.topic}
                  </span>
                  <span className="message-feed__message-time">
                    {formatTimestamp(message.timestamp)}
                  </span>
                </div>
                <div className="message-feed__message-payload">
                  <pre className="message-feed__message-content">
                    {formatPayload(message.payload)}
                  </pre>
                </div>
              </div>
            ))}

          </div>
        )}

        {/* Scroll to top button */}
        {showScrollButton && (
          <button
            className="message-feed__scroll-to-bottom"
            onClick={handleScrollToTop}
            aria-label="Scroll to latest messages"
            title="Scroll to latest messages"
          >
            ↑ New messages
          </button>
        )}
      </div>

      {/* Latest message summary */}
      {state.lastMessage && (
        <div className="message-feed__latest">
          <div className="message-feed__latest-header">
            <span className="message-feed__latest-label">Latest:</span>
            <span className="message-feed__latest-topic">
              {state.lastMessage.topic}
            </span>
            <span className="message-feed__latest-time">
              {formatTimestamp(state.lastMessage.timestamp)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
