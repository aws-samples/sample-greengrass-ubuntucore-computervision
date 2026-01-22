/**
 * MQTT Types and Interfaces
 */

export interface MqttMessage {
  topic: string;
  payload: string;
  timestamp: Date;
  qos: number;
}

export enum ConnectionStatus {
  DISCONNECTED = 'disconnected',
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  RECONNECTING = 'reconnecting',
  ERROR = 'error',
}

export interface MqttState {
  connected: boolean;
  messages: MqttMessage[];
  error: string | null;
  connectionStatus: ConnectionStatus;
  lastMessage: MqttMessage | null;
  messageCount: number;
}

export interface MqttError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface MqttConfig {
  endpoint?: string;
  topic: string;
  clientId?: string;
  keepAliveSeconds?: number;
  maxReconnectAttempts?: number;
}
