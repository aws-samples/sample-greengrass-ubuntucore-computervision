/**
 * IoT Shadow Service - Reads and updates AWS IoT Device Shadow state
 */

import { IoTDataPlaneClient, GetThingShadowCommand, UpdateThingShadowCommand } from '@aws-sdk/client-iot-data-plane';

const SHADOW_NAME = 'inference-config';

export interface InferenceConfig {
  confidence_threshold: number;
}

export class IotShadowService {
  private getClient(credentials: any, region: string): IoTDataPlaneClient {
    return new IoTDataPlaneClient({ region, credentials });
  }

  async getConfidenceThreshold(thingName: string, credentials: any, region: string): Promise<number | null> {
    try {
      const client = this.getClient(credentials, region);
      const command = new GetThingShadowCommand({ thingName, shadowName: SHADOW_NAME });
      const response = await client.send(command);
      const shadow = JSON.parse(new TextDecoder().decode(response.payload));
      return shadow?.state?.reported?.confidence_threshold ?? null;
    } catch (error: any) {
      if (error.name === 'ResourceNotFoundException') {
        return null;
      }
      throw error;
    }
  }

  async setConfidenceThreshold(thingName: string, credentials: any, region: string, threshold: number): Promise<void> {
    const client = this.getClient(credentials, region);
    const payload = JSON.stringify({
      state: { desired: { confidence_threshold: threshold } },
    });
    const command = new UpdateThingShadowCommand({
      thingName,
      shadowName: SHADOW_NAME,
      payload: new TextEncoder().encode(payload),
    });
    await client.send(command);
  }
}

export const iotShadowService = new IotShadowService();
