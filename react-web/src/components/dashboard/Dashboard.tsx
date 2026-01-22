/**
 * Main Dashboard Component - Layout container for authenticated users
 */

import React, { useCallback, useEffect, useRef } from 'react';
import { Header } from './Header';
import { ImageGallery } from './ImageGallery';
import { MessageFeed } from './MessageFeed';
import { S3BucketInput } from './S3BucketInput';
import { MqttTopicInput } from './MqttTopicInput';
import { S3Provider, useS3 } from '../../contexts/S3Context';
import { MqttProvider, useMqtt } from '../../contexts/MqttContext';

import { S3Object, S3Error } from '../../types/s3';
import './Dashboard.css';

export interface DashboardProps {
  children?: React.ReactNode;
  className?: string;
}

// Internal Dashboard Content Component that uses S3Context and MqttContext
const DashboardContent: React.FC<DashboardProps> = ({
  children,
  className = '',
}) => {
  const { state, actions: s3Actions } = useS3();
  const { state: mqttState } = useMqtt();
  const previousMessageCountRef = useRef<number>(0);

  /**
   * Handle S3 image gallery errors
   */
  const handleS3Error = useCallback((error: S3Error) => {
    console.error('S3 Gallery Error:', error);
  }, []);

  /**
   * Handle successful S3 image load
   */
  const handleImageClick = useCallback((image: S3Object) => {
    console.log('Image clicked:', image);
    // TODO: Implement image modal or detailed view
  }, []);

  /**
   * Handle MQTT topic change
   */
  const handleMqttTopicChange = useCallback((topic: string) => {
    console.log('MQTT topic changed:', topic);
    // TODO: Implement MQTT connection logic
  }, []);

  // Determine S3 status from context
  const getS3Status = () => {
    if (state.loading) return 'loading';
    if (state.error) return 'error';
    if (state.images.length > 0 || state.selectedBucket) return 'connected';
    return 'loading';
  };

  // Determine MQTT status from context
  const getMqttStatus = () => {
    if (mqttState.connected) return 'connected';
    if (mqttState.error) return 'error';
    if (
      mqttState.connectionStatus === 'connecting' ||
      mqttState.connectionStatus === 'reconnecting'
    )
      return 'loading';
    return 'disconnected';
  };

  /**
   * Auto-refresh S3 images when new MQTT messages are received
   */
  useEffect(() => {
    // Check if we have a new message (message count increased)
    if (mqttState.messageCount > previousMessageCountRef.current && 
        mqttState.messageCount > 0 && 
        state.selectedBucket && 
        !state.loading) {
      
      console.log(` New MQTT message received (count: ${mqttState.messageCount}), refreshing S3 images...`);
      
      // Add a small delay to avoid rapid refreshes
      const refreshTimeout = setTimeout(() => {
        s3Actions.refreshImages();
      }, 1000);

      // Update the previous count
      previousMessageCountRef.current = mqttState.messageCount;

      return () => clearTimeout(refreshTimeout);
    } else {
      // Update the previous count even if we don't refresh
      previousMessageCountRef.current = mqttState.messageCount;
    }
  }, [mqttState.messageCount, state.selectedBucket, state.loading, s3Actions]);

  const s3Status = getS3Status();
  const mqttStatus = getMqttStatus();

  return (
    <div className={`dashboard ${className}`} role="application" aria-label="Computer Vision Dashboard">
      {/* Header */}
      <Header />

      {/* Main Content Area */}
      <main id="main-content" className="dashboard__main" role="main">
        <div className="dashboard__container">
          {/* Welcome Section */}
          <section className="dashboard__welcome" aria-labelledby="welcome-title">
            {/* Configuration Section */}
            <div className="dashboard__configuration" role="region" aria-labelledby="config-title">
              <div className="dashboard__configuration-header">
                <h2 id="config-title" className="dashboard__configuration-title">Data Sources</h2>
                <p className="dashboard__configuration-description">
                  Connect to your S3 bucket for image storage and MQTT topic for real-time IoT messages
                </p>
              </div>
              
              <div className="dashboard__configuration-content">
                <div className="dashboard__configuration-inputs">
                  <S3BucketInput className="dashboard__configuration-input" />
                  <MqttTopicInput
                    className="dashboard__configuration-input"
                    onTopicChange={handleMqttTopicChange}
                  />
                </div>
                
                <div className="dashboard__configuration-status" role="status" aria-live="polite" aria-label="Connection status indicators">
                  <div className="dashboard__status-item dashboard__status-item--success" role="status" aria-label="Authentication status: Connected">
                    <div className="dashboard__status-indicator dashboard__status-indicator--success" aria-hidden="true"></div>
                    <div className="dashboard__status-text">
                      <span className="dashboard__status-label">
                        Authentication
                      </span>
                      <span className="dashboard__status-value">Connected</span>
                    </div>
                  </div>
                  <div
                    className={`dashboard__status-item dashboard__status-item--${
                      s3Status === 'connected'
                        ? 'success'
                        : s3Status === 'error'
                          ? 'error'
                          : 'pending'
                    }`}
                    role="status"
                    aria-label={`S3 Images status: ${
                      s3Status === 'connected'
                        ? 'Connected'
                        : s3Status === 'error'
                          ? 'Error'
                          : 'Loading'
                    }`}
                  >
                    <div className={`dashboard__status-indicator dashboard__status-indicator--${
                      s3Status === 'connected'
                        ? 'success'
                        : s3Status === 'error'
                          ? 'error'
                          : 'pending'
                    }`} aria-hidden="true"></div>
                    <div className="dashboard__status-text">
                      <span className="dashboard__status-label">S3 Images</span>
                      <span className="dashboard__status-value">
                        {s3Status === 'connected'
                          ? 'Connected'
                          : s3Status === 'error'
                            ? 'Error'
                            : 'Loading...'}
                      </span>
                    </div>
                  </div>
                  <div
                    className={`dashboard__status-item dashboard__status-item--${
                      mqttStatus === 'connected'
                        ? 'success'
                        : mqttStatus === 'error'
                          ? 'error'
                          : 'pending'
                    }`}
                    role="status"
                    aria-label={`IoT Messages status: ${
                      mqttStatus === 'connected'
                        ? 'Connected'
                        : mqttStatus === 'error'
                          ? 'Error'
                          : mqttStatus === 'loading'
                            ? 'Connecting'
                            : 'Disconnected'
                    }`}
                  >
                    <div className={`dashboard__status-indicator dashboard__status-indicator--${
                      mqttStatus === 'connected'
                        ? 'success'
                        : mqttStatus === 'error'
                          ? 'error'
                          : 'pending'
                    }`} aria-hidden="true"></div>
                    <div className="dashboard__status-text">
                      <span className="dashboard__status-label">
                        IoT Messages
                      </span>
                      <span className="dashboard__status-value">
                        {mqttStatus === 'connected'
                          ? 'Connected'
                          : mqttStatus === 'error'
                            ? 'Error'
                            : mqttStatus === 'loading'
                              ? 'Connecting...'
                              : 'Disconnected'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* Content Grid */}
          <section className="dashboard__content" aria-label="Dashboard content">
            <div className="dashboard__grid">
              {/* S3 Image Gallery */}
              <article className="dashboard__card dashboard__card--images" aria-labelledby="image-gallery-title">
                <ImageGallery
                  className="dashboard__image-gallery"
                  onImageClick={handleImageClick}
                  onError={handleS3Error}
                />
              </article>

              {/* MQTT Message Feed */}
              <article className="dashboard__card dashboard__card--messages" aria-labelledby="message-feed-title">
                <MessageFeed
                  className="dashboard__message-feed"
                  maxMessages={50}
                  showConnectionStatus={true}
                />
              </article>
            </div>
          </section>

          {/* Custom children content */}
          {children && (
            <section className="dashboard__custom">{children}</section>
          )}
        </div>
      </main>
    </div>
  );
};
// Main Dashboard Component that provides S3Context and MqttContext
export const Dashboard: React.FC<DashboardProps> = ({ children, className }) => {
  return (
    <S3Provider autoRefreshInterval={30000} maxImages={20}>
      <MqttProvider autoConnect={false}>
        <DashboardContent children={children} className={className} />
      </MqttProvider>
    </S3Provider>
  );
};
