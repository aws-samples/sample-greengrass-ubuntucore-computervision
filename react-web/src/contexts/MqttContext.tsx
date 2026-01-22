/**
 * MQTT Context - Manages MQTT state and provides real-time messaging
 */

import React, {
  createContext,
  useContext,
  useReducer,
  useEffect,
  useCallback,
  ReactNode,
} from 'react';
import { MqttMessage, MqttState, ConnectionStatus } from '../types/mqtt';
import { useAuthenticatedAWS } from '../hooks/useAuthenticatedAWS';
import { mqttService } from '../services/mqttService';

// MQTT Context Actions
type MqttAction =
  | { type: 'SET_CONNECTING' }
  | { type: 'SET_CONNECTED' }
  | { type: 'SET_DISCONNECTED' }
  | { type: 'SET_RECONNECTING' }
  | { type: 'SET_ERROR'; payload: string }
  | { type: 'ADD_MESSAGE'; payload: MqttMessage }
  | { type: 'CLEAR_MESSAGES' }
  | { type: 'SET_STATUS'; payload: ConnectionStatus }
  | { type: 'RESET_STATE' };

// MQTT Context Value
interface MqttContextValue {
  state: MqttState;
  actions: {
    connect: (topic: string) => Promise<void>;
    disconnect: () => Promise<void>;
    clearMessages: () => void;
    clearError: () => void;
    reset: () => void;
  };
}

// Initial state
const initialState: MqttState = {
  connected: false,
  messages: [],
  error: null,
  connectionStatus: ConnectionStatus.DISCONNECTED,
  lastMessage: null,
  messageCount: 0,
};

// Reducer
function mqttReducer(state: MqttState, action: MqttAction): MqttState {
  switch (action.type) {
    case 'SET_CONNECTING':
      return {
        ...state,
        connected: false,
        connectionStatus: ConnectionStatus.CONNECTING,
        error: null,
      };
    case 'SET_CONNECTED':
      return {
        ...state,
        connected: true,
        connectionStatus: ConnectionStatus.CONNECTED,
        error: null,
      };
    case 'SET_DISCONNECTED':
      return {
        ...state,
        connected: false,
        connectionStatus: ConnectionStatus.DISCONNECTED,
      };
    case 'SET_RECONNECTING':
      return {
        ...state,
        connected: false,
        connectionStatus: ConnectionStatus.RECONNECTING,
        error: null,
      };
    case 'SET_ERROR':
      return {
        ...state,
        connected: false,
        connectionStatus: ConnectionStatus.ERROR,
        error: action.payload,
      };
    case 'ADD_MESSAGE':
      return {
        ...state,
        messages: [action.payload, ...state.messages].slice(0, 100), // Keep last 100 messages
        lastMessage: action.payload,
        messageCount: state.messageCount + 1,
      };
    case 'CLEAR_MESSAGES':
      return {
        ...state,
        messages: [],
        lastMessage: null,
        messageCount: 0,
      };
    case 'SET_STATUS':
      return {
        ...state,
        connectionStatus: action.payload,
        connected: action.payload === ConnectionStatus.CONNECTED,
      };
    case 'RESET_STATE':
      return initialState;
    default:
      return state;
  }
}

// Create context
const MqttContext = createContext<MqttContextValue | undefined>(undefined);

// MQTT Provider Props
interface MqttProviderProps {
  children: ReactNode;
  defaultTopic?: string;
  autoConnect?: boolean;
}

// MQTT Provider Component
export const MqttProvider: React.FC<MqttProviderProps> = ({
  children,
  defaultTopic = 'dashboard/messages',
  autoConnect = true,
}) => {
  const [state, dispatch] = useReducer(mqttReducer, initialState);
  const { credentials, isAuthenticated, region } = useAuthenticatedAWS();

  /**
   * Handle incoming MQTT messages
   */
  const handleMessage = useCallback((message: MqttMessage) => {
    console.log('Received MQTT message:', message);
    dispatch({ type: 'ADD_MESSAGE', payload: message });
  }, []);

  /**
   * Handle connection status changes
   */
  const handleStatusChange = useCallback((status: ConnectionStatus) => {
    console.log('MQTT status changed:', status);
    dispatch({ type: 'SET_STATUS', payload: status });
  }, []);

  /**
   * Connect to MQTT
   */
  const connect = useCallback(
    async (topic: string) => {
      if (!topic || !topic.trim()) {
        console.log('No topic provided for MQTT connection');
        dispatch({ type: 'SET_ERROR', payload: 'Topic is required' });
        return;
      }

      if (!isAuthenticated || !credentials) {
        console.log('Not authenticated, cannot connect to MQTT');
        dispatch({ type: 'SET_ERROR', payload: 'Authentication required' });
        return;
      }

      try {
        console.log(` Connecting to MQTT topic: ${topic}`);
        dispatch({ type: 'SET_CONNECTING' });

        // Initialize MQTT service
        await mqttService.initialize(credentials, region);

        // Set up callbacks
        mqttService.onMessage(handleMessage);
        mqttService.onStatusChange(handleStatusChange);

        // Connect
        await mqttService.connect(topic);

        console.log('Successfully connected to MQTT');
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : 'Failed to connect to MQTT';
        console.error('Failed to connect to MQTT:', error);
        dispatch({ type: 'SET_ERROR', payload: errorMessage });
      }
    },
    [
      isAuthenticated,
      credentials,
      region,
      handleMessage,
      handleStatusChange,
    ]
  );

  /**
   * Disconnect from MQTT
   */
  const disconnect = useCallback(async () => {
    try {
      console.log('Disconnecting from MQTT...');

      // Remove callbacks
      mqttService.removeMessageCallback(handleMessage);
      mqttService.removeStatusCallback(handleStatusChange);

      // Disconnect
      await mqttService.disconnect();

      dispatch({ type: 'SET_DISCONNECTED' });
      console.log('Disconnected from MQTT');
    } catch (error) {
      console.error('Failed to disconnect from MQTT:', error);
    }
  }, [handleMessage, handleStatusChange]);

  /**
   * Clear messages
   */
  const clearMessages = useCallback(() => {
    dispatch({ type: 'CLEAR_MESSAGES' });
  }, []);

  /**
   * Clear error
   */
  const clearError = useCallback(() => {
    dispatch({ type: 'SET_ERROR', payload: '' });
  }, []);

  /**
   * Reset state
   */
  const reset = useCallback(() => {
    console.log('Resetting MQTT state');
    dispatch({ type: 'RESET_STATE' });
  }, []);

  // Only reset when authentication changes, don't auto-connect
  useEffect(() => {
    if (!isAuthenticated) {
      console.log('Not authenticated, resetting MQTT state');
      disconnect();
      reset();
    }
  }, [isAuthenticated, disconnect, reset]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  const contextValue: MqttContextValue = {
    state,
    actions: {
      connect,
      disconnect,
      clearMessages,
      clearError,
      reset,
    },
  };

  return (
    <MqttContext.Provider value={contextValue}>{children}</MqttContext.Provider>
  );
};

// Hook to use MQTT context
export const useMqtt = (): MqttContextValue => {
  const context = useContext(MqttContext);
  if (context === undefined) {
    throw new Error('useMqtt must be used within an MqttProvider');
  }
  return context;
};

// Export context for advanced usage
export { MqttContext };
