/**
 * BEHAVIOR SPEC
 * 
 * Given a VoxQuery session initialized with Clerk auth,
 * when the session lifecycle begins,
 * then it coordinates the 3 WebSocket connections (audio, pipeline, tts)
 * and correctly handles a clarification request followed by a resume action.
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { useVoxQuerySession, VoxQueryAuthRelay } from './useVoxQuerySession';
import { vi, describe, it, expect, beforeEach } from 'vitest';

// Mocking browser globals
const mockWebSocketInstances: any[] = [];
const mockWebSocket = vi.fn();
class MockWebSocket {
  onopen: any;
  onmessage: any;
  onerror: any;
  onclose: any;
  readyState = 1; // OPEN
  send = vi.fn();
  close = vi.fn();
  constructor(url: string) {
    mockWebSocketInstances.push(this);
    mockWebSocket(url);
  }
}
global.WebSocket = MockWebSocket as any;

class MockAudioContext {
  state = 'running';
  suspend = vi.fn().mockResolvedValue(undefined);
  resume = vi.fn().mockResolvedValue(undefined);
  close = vi.fn().mockResolvedValue(undefined);
}
global.AudioContext = MockAudioContext as any;

// Mock fetch and API calls
vi.mock('../../lib/api', () => ({
  audioSocketUrl: (s: string) => `ws://audio/${s}`,
  pipelineSocketUrl: (s: string) => `ws://pipeline/${s}`,
  ttsSocketUrl: (s: string) => `ws://tts/${s}`,
  createSession: vi.fn().mockResolvedValue({ session_id: 'sess-123', conversation_id: 'conv-123' }),
  deleteSession: vi.fn().mockResolvedValue(true),
  fetchResult: vi.fn().mockResolvedValue({
    turn_id: 'turn-123',
    confidence_tier: 'High',
    chart_type: 'Stat',
    proactive_questions: []
  }),
  submitQuery: vi.fn().mockResolvedValue({ turn_id: 'turn-123' }),
  postClarification: vi.fn().mockResolvedValue(true)
}));

describe('useVoxQuerySession', () => {
  let authRelay: VoxQueryAuthRelay;

  beforeEach(() => {
    vi.clearAllMocks();
    authRelay = {
      mode: 'clerk',
      ready: true,
      signedIn: true,
      getToken: vi.fn().mockResolvedValue('fake-token')
    };
  });

  it('coordinates session lifecycle and clarification resume', async () => {
    const { result, unmount } = renderHook(() => useVoxQuerySession(authRelay));

    // Initially waiting for session creation
    expect(result.current.isReady).toBe(false);

    // Wait for session to be created
    await waitFor(() => {
      expect(result.current.isReady).toBe(true);
      expect(result.current.session.sessionId).toBe('sess-123');
    });

    // Submit a query
    await act(async () => {
      await result.current.submitQuery('show me revenue');
    });

    await waitFor(() => {
      console.log('NOTICE:', result.current.notice);
      console.log('TURN STATE:', result.current.turnState);
      expect(result.current.pipelineInFlight).toBe(true);
      expect(result.current.turnState).toBe('accepted');
    });

    // Simulate clarification request
    await act(async () => {
      const socketInstance = mockWebSocketInstances[0];
      if (socketInstance && socketInstance.onmessage) {
        socketInstance.onmessage({
          data: JSON.stringify({ type: 'clarification_request', turn_id: 'turn-123', question: 'test', options: ['A'] })
        });
      }
    });

    await waitFor(() => {
      expect(result.current.clarification.pending).toBe(true);
      expect(result.current.turnState).toBe('clarification_required');
    });

    // Submit clarification
    await act(async () => {
      await result.current.submitClarification('A');
    });

    await waitFor(() => {
      expect(result.current.turnState).toBe('executing');
    });

    // Clean up
    unmount();
  });
});
