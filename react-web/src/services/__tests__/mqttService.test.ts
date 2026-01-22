/**
 * MQTT Service Tests
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mqttService } from '../mqttService';
import { ConnectionStatus } from '../../types/mqtt';

// Mock the AWS IoT Device SDK
vi.mock('aws-iot-device-sdk-v2', () => ({
  mqtt: {
    MqttClient: vi.fn(),
    QoS: {
      AtLeastOnce: 1,
    },
  },
  iot: {
    AwsIotMqttConnectionConfigBuilder: {
      new_with_websockets: vi.fn(() => ({
        with_endpoint: vi.fn().mockReturnThis(),
        with_client_id: vi.fn().mockReturnThis(),
        with_clean_session: vi.fn().mockReturnThis(),
        with_keep_alive_seconds: vi.fn().mockReturnThis(),
        build: vi.fn(),
      })),
    },
  },
  auth: {
    AwsCredentialsProvider: {
      newStatic: vi.fn(),
    },
  },
  io: {
    ClientBootstrap: vi.fn(),
  },
}));

// Mock the DiscoveryService
vi.mock('../discoveryService', () => ({
  discoveryService: {
    discoverIoTEndpoint: vi.fn().mockResolvedValue('test-endpoint.iot.amazonaws.com'),
  },
}));

describe('MqttService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Initialization', () => {
    it('should initialize with credentials and region', async () => {
      const mockCredentials = {
        accessKeyId: 'test-key',
        secretAccessKey: 'test-secret',
        sessionToken: 'test-token',
      };

      await expect(
        mqttService.initialize(mockCredentials, 'us-east-1')
      ).resolves.not.toThrow();
    });

    it('should use DiscoveryService to get IoT endpoint', async () => {
      const mockCredentials = {
        accessKeyId: 'test-key',
        secretAccessKey: 'test-secret',
        sessionToken: 'test-token',
      };

      await mqttService.initialize(mockCredentials, 'us-east-1');

      const { discoveryService } = await import('../discoveryService');
      expect(discoveryService.discoverIoTEndpoint).toHaveBeenCalledWith('us-east-1');
    });

    it('should use provided endpoint if given', async () => {
      const mockCredentials = {
        accessKeyId: 'test-key',
        secretAccessKey: 'test-secret',
        sessionToken: 'test-token',
      };

      const customEndpoint = 'custom-endpoint.iot.amazonaws.com';
      await mqttService.initialize(mockCredentials, 'us-east-1', customEndpoint);

      const { discoveryService } = await import('../discoveryService');
      expect(discoveryService.discoverIoTEndpoint).not.toHaveBeenCalled();
    });
  });

  describe('Connection Status', () => {
    it('should start with DISCONNECTED status', () => {
      expect(mqttService.getConnectionStatus()).toBe(ConnectionStatus.DISCONNECTED);
    });
  });

  describe('Callbacks', () => {
    it('should add and remove message callbacks', () => {
      const callback = vi.fn();
      
      mqttService.onMessage(callback);
      mqttService.removeMessageCallback(callback);
      
      // Should not throw
      expect(true).toBe(true);
    });

    it('should add and remove status callbacks', () => {
      const callback = vi.fn();
      
      mqttService.onStatusChange(callback);
      mqttService.removeStatusCallback(callback);
      
      // Should not throw
      expect(true).toBe(true);
    });
  });

  describe('Error Handling', () => {
    it('should handle initialization errors gracefully', async () => {
      const { discoveryService } = await import('../discoveryService');
      vi.mocked(discoveryService.discoverIoTEndpoint).mockRejectedValueOnce(
        new Error('Discovery failed')
      );

      const mockCredentials = {
        accessKeyId: 'test-key',
        secretAccessKey: 'test-secret',
        sessionToken: 'test-token',
      };

      await expect(
        mqttService.initialize(mockCredentials, 'us-east-1')
      ).rejects.toThrow('MQTT Service initialization failed');
    });
  });
});