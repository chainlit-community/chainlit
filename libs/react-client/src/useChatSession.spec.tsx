// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { ReactNode } from 'react';
import { RecoilRoot, useRecoilValue } from 'recoil';
import { describe, expect, it, vi } from 'vitest';

import { ChainlitContext } from './context';
import { elementState } from './state';
import { IElement, IThread } from './types';
import { useChatSession } from './useChatSession';

const handlers: Record<string, (...args: any[]) => void> = {};

vi.mock('lodash', async (importOriginal) => ({
  ...(await importOriginal<typeof import('lodash')>()),
  debounce: (fn: unknown) => fn
}));

// The audio worklets need browser Blob URLs that jsdom can't provide.
vi.mock('./wavtools', () => ({
  WavRecorder: class {},
  WavStreamPlayer: class {}
}));

vi.mock('socket.io-client', () => ({
  default: () => ({
    auth: {},
    on: (event: string, handler: (...args: any[]) => void) => {
      handlers[event] = handler;
    },
    emit: vi.fn(),
    removeAllListeners: vi.fn(),
    close: vi.fn()
  })
}));

const client = {
  httpEndpoint: 'http://localhost:8000',
  type: 'webapp',
  stickyCookie: vi.fn(),
  getElementUrl: (id: string, sessionId: string) =>
    `/project/file/${id}?session_id=${sessionId}`
};

const wrapper = ({ children }: { children: ReactNode }) => (
  <RecoilRoot>
    <ChainlitContext.Provider value={client as any}>
      {children}
    </ChainlitContext.Provider>
  </RecoilRoot>
);

describe('useChatSession resume_thread', () => {
  it('resolves missing element URLs from chainlitKey', async () => {
    const { result } = renderHook(
      () => ({
        session: useChatSession(),
        elements: useRecoilValue(elementState)
      }),
      { wrapper }
    );
    await act(async () => {
      await result.current.session.connect({ userEnv: {} });
    });

    const stored = { id: 'e2', type: 'image', url: 'https://cdn/e2.png' };
    act(() => {
      handlers['resume_thread']({
        id: 'thread-1',
        steps: [],
        elements: [{ id: 'e1', type: 'file', chainlitKey: 'key-1' }, stored]
      } as unknown as IThread);
    });

    const urls = result.current.elements.map((e: IElement) => e.url);
    expect(urls).toEqual([
      `/project/file/key-1?session_id=${result.current.session.sessionId}`,
      'https://cdn/e2.png'
    ]);
  });
});
