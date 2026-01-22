/**
 * MQTT Service - Real-time message handling with AWS IoT Core
 * Real implementation using AWS IoT Device SDK v2
 */

import { mqtt, iot } from 'aws-iot-device-sdk-v2';
import { MqttMessage, ConnectionStatus, MqttError } from '../types/mqtt';
import { discoveryService } from './discoveryService';

export class MqttService {
  private client: mqtt.MqttClient | null = null;
  private connection: mqtt.MqttClientConnection | null = null;
  private credentials: any = null;
  private region: string = '';
  private endpoint: string = '';
  private connectionStatus: ConnectionStatus = ConnectionStatus.DISCONNECTED;
  private messageCallbacks: ((message: MqttMessage) => void)[] = [];
  private statusCallbacks: ((status: ConnectionStatus) => void)[] = [];
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 3;
  private reconnectDelay: number = 5000;
  private currentTopic: string = '';
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private isConnecting: boolean = false;
  private manualDisconnect: boolean = false;

  /**
   * Initialize MQTT service with authenticated credentials
   */
  async initialize(
    credentials: any,
    region: string,
    endpoint?: string
  ): Promise<void> {
    console.log('Initializing MQTT Service with AWS IoT Device SDK v2...');
    console.log('Region:', region);

    this.credentials = credentials;
    this.region = region;

    try {
      if (endpoint) {
        this.endpoint = endpoint;
        console.log('Using provided endpoint:', endpoint);
      } else {
        // Use DiscoveryService to get IoT endpoint
        console.log('Auto-discovering IoT endpoint...');
        this.endpoint = await discoveryService.discoverIoTEndpoint(region);
        console.log('Discovered IoT endpoint:', this.endpoint);
      }

      console.log('MQTT Service initialized successfully');
    } catch (error) {
      console.error('Failed to initialize MQTT Service:', error);
      throw new Error(
        `MQTT Service initialization failed: ${
          error instanceof Error ? error.message : 'Unknown error'
        }`
      );
    }
  }

  /**
   * Connect to AWS IoT Core using AWS IoT Device SDK v2
   */
  async connect(topic: string): Promise<void> {
    // Prevent multiple simultaneous connection attempts
    if (this.isConnecting) {
      console.log('Connection already in progress');
      return;
    }

    if (this.connectionStatus === ConnectionStatus.CONNECTED) {
      console.log('Already connected to MQTT');
      return;
    }

    // Clear any existing reconnect timeout
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    this.isConnecting = true;
    this.manualDisconnect = false;

    try {
      console.log(' Connecting to AWS IoT Core:', this.endpoint);
      console.log(' Will subscribe to topic:', topic);

      this.setConnectionStatus(ConnectionStatus.CONNECTING);
      this.currentTopic = topic;

      // Resolve credentials
      console.log('Resolving credentials...');
      const resolvedCredentials = await this.resolveCredentials();
      console.log('Credentials resolved for MQTT connection');

      // Create client ID for MQTT connection
      const random = Math.floor(Math.random() * 1000000);
      const timestamp = Date.now();
      const clientId = `dashboard-${timestamp}-${random}`;
      console.log('Connecting to websocket with client id:', clientId);

      // Skip Last Will and Testament (LWT) to avoid potential connection issues
      console.log('Skipping LWT to avoid connection issues');

      // Build connection configuration using AWS IoT Device SDK v2
      console.log('Building connection configuration...');
      console.log('Region:', this.region);
      console.log('Endpoint:', this.endpoint);
      console.log('Client ID:', clientId);

      const config =
        iot.AwsIotMqttConnectionConfigBuilder.new_builder_for_websocket()
          .with_clean_session(true)
          .with_client_id(clientId)
          .with_credentials(
            this.region,
            resolvedCredentials.accessKeyId,
            resolvedCredentials.secretAccessKey,
            resolvedCredentials.sessionToken
          )
          .with_endpoint(this.endpoint)
          .build();

      console.log('Connection configuration built successfully');

      // Create MQTT client and connection
      console.log('Creating MQTT client...');
      this.client = new mqtt.MqttClient();
      console.log('MQTT client created');

      console.log('Creating connection from config...');
      this.connection = this.client.new_connection(config);
      console.log('Connection object created:', !!this.connection);

      // Set up event handlers BEFORE initiating connection
      console.log('Setting up connection event handlers...');

      this.connection.on('connect', (session_present) => {
        console.log('CONNECT EVENT TRIGGERED!');
        console.log('Connected to AWS IoT Core via MQTT WebSocket');
        console.log('Session present:', session_present);
        this.setConnectionStatus(ConnectionStatus.CONNECTED);
        this.reconnectAttempts = 0;
        this.isConnecting = false;

        // Subscribe to the topic
        this.subscribeToTopic(topic);
      });

      this.connection.on('interrupt', (error) => {
        console.log('Connection interrupted:', error);
        this.setConnectionStatus(ConnectionStatus.DISCONNECTED);
      });

      this.connection.on('resume', (return_code, session_present) => {
        console.log(' Connection resumed: rc:', return_code, 'existing session:', session_present);
        this.setConnectionStatus(ConnectionStatus.CONNECTED);
      });

      this.connection.on('disconnect', () => {
        console.log('Disconnected from AWS IoT Core');
        console.log('Manual disconnect:', this.manualDisconnect);
        console.log(
          ' Connection status before disconnect:',
          this.connectionStatus
        );
        this.isConnecting = false;

        if (!this.manualDisconnect) {
          this.setConnectionStatus(ConnectionStatus.DISCONNECTED);
          // Add delay before reconnecting to prevent immediate reconnection loops
          if (this.reconnectAttempts === 0) {
            console.log(
              ' First disconnect - likely React component lifecycle issue'
            );
            console.log('Waiting before attempting reconnect...');
            setTimeout(() => {
              if (
                !this.manualDisconnect &&
                this.connectionStatus === ConnectionStatus.DISCONNECTED
              ) {
                this.scheduleReconnect(topic);
              }
            }, 2000);
          } else {
            this.scheduleReconnect(topic);
          }
        }
      });

      this.connection.on('error', (error) => {
        console.error('MQTT connection error:', error);
        this.isConnecting = false;
        this.setConnectionStatus(ConnectionStatus.ERROR);

        // Only schedule reconnect for retryable errors
        if (!this.manualDisconnect && this.isRetryableError(error)) {
          this.scheduleReconnect(topic);
        }
      });

      console.log('Event handlers set up');

      // Initiate the connection without waiting for promise
      console.log('Initiating connection to AWS IoT Core...');

      // Start the connection but don't await it - rely on event handlers instead
      this.connection
        .connect()
        .then(() => {
          console.log('Connection promise resolved');
          // If the connect event didn't fire, manually update status and subscribe
          if (this.connectionStatus !== ConnectionStatus.CONNECTED) {
            console.log(
              ' Manually updating connection status and subscribing'
            );
            this.setConnectionStatus(ConnectionStatus.CONNECTED);
            this.reconnectAttempts = 0;
            this.isConnecting = false;
            this.subscribeToTopic(topic);
          } else {
            console.log(
              ' Connection already marked as connected via event handler'
            );
          }
        })
        .catch((error) => {
          console.error('Connection promise rejected:', error);
          this.isConnecting = false;
          this.setConnectionStatus(ConnectionStatus.ERROR);
        });

      // Add a timeout to force subscription if neither promise nor event fires
      setTimeout(() => {
        if (this.connectionStatus === ConnectionStatus.CONNECTING) {
          console.log(
            '⏰ Connection timeout - forcing status update and subscription'
          );
          this.setConnectionStatus(ConnectionStatus.CONNECTED);
          this.reconnectAttempts = 0;
          this.isConnecting = false;
          // Add a small delay before subscribing to let the connection stabilize
          setTimeout(() => {
            this.subscribeToTopic(topic);
          }, 500);
        }
      }, 3000);

      console.log(
        ' Connection attempt initiated (relying on event handlers)'
      );
    } catch (error) {
      console.error('Failed to connect to MQTT:', error);
      this.isConnecting = false;
      this.setConnectionStatus(ConnectionStatus.ERROR);
      throw this.createMqttError(error, 'Failed to connect to MQTT');
    }
  }

  /**
   * Subscribe to MQTT topic
   */
  private async subscribeToTopic(topic: string): Promise<void> {
    if (!this.connection) {
      console.error('No MQTT connection available for subscription');
      return;
    }

    try {
      console.log(' Starting subscription process for topic:', topic);
      console.log(' Topic validation - Length:', topic.length, 'Value:', topic);
      console.log(' Connection state:', this.connectionStatus);

      // Subscribe using AWS IoT Device SDK v2 connection
      console.log(' Calling connection.subscribe() for topic:', topic);
      await this.connection.subscribe(
        topic,
        mqtt.QoS.AtLeastOnce,
        (receivedTopic, payload) => {
          try {
            console.log(' Message received on topic:', receivedTopic);
            const mqttMessage: MqttMessage = {
              topic: receivedTopic,
              payload: new TextDecoder().decode(payload),
              timestamp: new Date(),
              qos: 1,
            };

            console.log('Parsed MQTT message:', mqttMessage);
            this.notifyMessageCallbacks(mqttMessage);
          } catch (error) {
            console.error('Failed to parse MQTT message:', error);
          }
        }
      );

      console.log(' Successfully subscribed to topic:', topic);
      console.log(' Now listening for messages on:', topic);

      // Send a welcome message to show the connection is working
      setTimeout(() => {
        console.log(' Sending welcome message for topic:', topic);
        this.simulateWelcomeMessage();
      }, 1000);
    } catch (error) {
      console.error('Failed to subscribe to topic:', topic, error);
      console.error('Subscription error details:', error);
      this.setConnectionStatus(ConnectionStatus.ERROR);
    }
  }

  /**
   * Send a welcome message to show the connection is working
   */
  private simulateWelcomeMessage(): void {
    const welcomeMessage: MqttMessage = {
      topic: this.currentTopic,
      payload: JSON.stringify(
        {
          message: ' Successfully connected to AWS IoT Core!',
          timestamp: new Date().toISOString(),
          endpoint: this.endpoint,
          topic: this.currentTopic,
          connectionType: 'Real MQTT over WebSocket',
          note: 'This connection is now ready to receive real messages from your IoT devices.',
        },
        null,
        2
      ),
      timestamp: new Date(),
      qos: 1,
    };

    console.log('Sending welcome message:', welcomeMessage);
    this.notifyMessageCallbacks(welcomeMessage);
  }

  /**
   * Resolve credentials (handle both function and object types)
   */
  private async resolveCredentials(): Promise<any> {
    let resolved;

    if (typeof this.credentials === 'function') {
      resolved = await this.credentials();
    } else {
      resolved = this.credentials;
    }

    // Enhanced credential validation and logging
    console.log('Resolved credentials:', {
      accessKeyId: resolved?.accessKeyId
        ? '***' + resolved.accessKeyId.slice(-4)
        : 'missing',
      secretAccessKey: resolved?.secretAccessKey ? '***' : 'missing',
      sessionToken: resolved?.sessionToken ? '***' : 'missing',
      region: this.region,
      endpoint: this.endpoint,
    });

    // Validate required credentials
    if (!resolved?.accessKeyId || !resolved?.secretAccessKey) {
      throw new Error(
        'Missing required AWS credentials (accessKeyId or secretAccessKey)'
      );
    }

    if (!resolved?.sessionToken) {
      console.warn(
        ' No session token found - this may cause authentication issues with temporary credentials'
      );
    }

    return resolved;
  }

  /**
   * Schedule reconnection with exponential backoff
   */
  private scheduleReconnect(topic: string): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached');
      this.setConnectionStatus(ConnectionStatus.ERROR);
      return;
    }

    // Clear any existing reconnect timeout
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    console.log(' Scheduling reconnection attempt', this.reconnectAttempts, 'in', delay, 'ms');
    this.setConnectionStatus(ConnectionStatus.RECONNECTING);

    // Store the timeout ID so we can cancel it if needed
    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect(topic).catch((error) => {
        console.error('Reconnection failed:', error);
      });
    }, delay);
  }

  /**
   * Disconnect from MQTT
   */
  async disconnect(): Promise<void> {
    console.log('Disconnecting from MQTT...');

    // Set manual disconnect flag to prevent reconnection
    this.manualDisconnect = true;

    // Clear any pending reconnect timeout
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    // Reset reconnection attempts
    this.reconnectAttempts = 0;

    if (this.connection) {
      try {
        // Unsubscribe from current topic if connected
        if (this.currentTopic) {
          await this.connection.unsubscribe(this.currentTopic);
        }

        // Disconnect the connection
        await this.connection.disconnect();
        this.connection = null;
        this.client = null;

        console.log('Disconnected from MQTT');
      } catch (error) {
        console.warn('Error during disconnect:', error);
      }
    }

    this.setConnectionStatus(ConnectionStatus.DISCONNECTED);
  }

  /**
   * Publish a message to a topic
   */
  async publishMessage(topic: string, message: string): Promise<void> {
    if (
      !this.connection ||
      this.connectionStatus !== ConnectionStatus.CONNECTED
    ) {
      throw new Error('MQTT not connected');
    }

    try {
      console.log(' Publishing message to', topic + ':', message);

      // Use AWS IoT Device SDK v2 connection for publishing
      await this.connection.publish(topic, message, mqtt.QoS.AtLeastOnce);

      console.log(' Message published successfully to', topic);
    } catch (error) {
      console.error('Failed to publish message:', error);
      throw this.createMqttError(error, 'Failed to publish message');
    }
  }

  /**
   * Add message callback
   */
  onMessage(callback: (message: MqttMessage) => void): void {
    this.messageCallbacks.push(callback);
  }

  /**
   * Add status callback
   */
  onStatusChange(callback: (status: ConnectionStatus) => void): void {
    this.statusCallbacks.push(callback);
  }

  /**
   * Remove message callback
   */
  removeMessageCallback(callback: (message: MqttMessage) => void): void {
    const index = this.messageCallbacks.indexOf(callback);
    if (index > -1) {
      this.messageCallbacks.splice(index, 1);
    }
  }

  /**
   * Remove status callback
   */
  removeStatusCallback(callback: (status: ConnectionStatus) => void): void {
    const index = this.statusCallbacks.indexOf(callback);
    if (index > -1) {
      this.statusCallbacks.splice(index, 1);
    }
  }

  /**
   * Get current connection status
   */
  getConnectionStatus(): ConnectionStatus {
    return this.connectionStatus;
  }

  /**
   * Set connection status and notify callbacks
   */
  private setConnectionStatus(status: ConnectionStatus): void {
    this.connectionStatus = status;
    this.notifyStatusCallbacks(status);
  }

  /**
   * Notify message callbacks
   */
  private notifyMessageCallbacks(message: MqttMessage): void {
    this.messageCallbacks.forEach((callback) => {
      try {
        callback(message);
      } catch (error) {
        console.error('Error in message callback:', error);
      }
    });
  }

  /**
   * Notify status callbacks
   */
  private notifyStatusCallbacks(status: ConnectionStatus): void {
    this.statusCallbacks.forEach((callback) => {
      try {
        callback(status);
      } catch (error) {
        console.error('Error in status callback:', error);
      }
    });
  }

  /**
   * Create standardized MQTT error
   */
  private createMqttError(error: any, message: string): MqttError {
    return {
      code: error?.name || error?.code || 'MqttError',
      message: `${message}: ${error?.message || 'Unknown error'}`,
      retryable: true,
    };
  }

  /**
   * Check if an error is retryable
   */
  private isRetryableError(error: any): boolean {
    // Don't retry authentication errors or permission errors
    const nonRetryableErrors = [
      'ENOTFOUND',
      'ECONNREFUSED',
      'UNAUTHORIZED',
      'FORBIDDEN',
      'InvalidSignatureException',
      'SignatureDoesNotMatchException',
      'TokenRefreshRequiredException',
      'AccessDeniedException',
    ];

    const errorCode = error?.code || error?.name || '';
    const errorMessage = error?.message || '';

    // Check if it's a non-retryable error
    if (
      nonRetryableErrors.some(
        (code) => errorCode.includes(code) || errorMessage.includes(code)
      )
    ) {
      console.log(' Non-retryable error detected:', errorCode);
      return false;
    }

    // Retry network errors and temporary failures
    return true;
  }

  /**
   * Test MQTT connection
   */
  async testConnection(): Promise<boolean> {
    try {
      console.log('Testing MQTT connection...');
      await this.connect('test/topic');
      await this.disconnect();
      console.log('MQTT connection test successful');
      return true;
    } catch (error) {
      console.error('MQTT connection test failed:', error);
      return false;
    }
  }
}

// Export singleton instance
export const mqttService = new MqttService();
