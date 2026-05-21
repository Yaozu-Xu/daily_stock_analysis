import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import * as AuthContext from './contexts/AuthContext';

const { setCurrentRoute, useAgentChatStoreMock } = vi.hoisted(() => {
  const setCurrentRoute = vi.fn();
  const state = { completionBadge: false };
  const useAgentChatStoreMock = Object.assign(
    vi.fn((selector?: (value: typeof state) => unknown) => (selector ? selector(state) : state)),
    { getState: () => ({ setCurrentRoute }) },
  );
  return { setCurrentRoute, useAgentChatStoreMock };
});

vi.mock('./contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: vi.fn(),
}));

vi.mock('./stores/agentChatStore', () => ({
  useAgentChatStore: useAgentChatStoreMock,
}));

vi.mock('./pages/HomePage', () => ({
  default: () => <div data-testid="home-page">Home</div>,
}));

vi.mock('./pages/ChatPage', () => ({
  default: () => <div data-testid="chat-page">Chat</div>,
}));

vi.mock('./pages/PortfolioPage', () => ({
  default: () => <div data-testid="portfolio-page">Portfolio</div>,
}));

vi.mock('./pages/BacktestPage', () => ({
  default: () => <div data-testid="backtest-page">Backtest</div>,
}));

vi.mock('./pages/AlertsPage', () => ({
  default: () => <div data-testid="alerts-page">Alerts</div>,
}));

vi.mock('./pages/SettingsPage', () => ({
  default: () => <div data-testid="settings-page">Settings</div>,
}));

vi.mock('./pages/NotFoundPage', () => ({
  default: () => <div data-testid="not-found-page">Not Found</div>,
}));

vi.mock('./pages/LoginPage', () => ({
  default: () => <div data-testid="login-page">Login</div>,
}));

beforeEach(() => {
  vi.clearAllMocks();
  window.history.pushState({}, '', '/');
  vi.mocked(AuthContext.useAuth).mockReturnValue({
    authEnabled: false,
    loggedIn: false,
    passwordSet: false,
    passwordChangeable: false,
    setupState: 'no_password',
    isLoading: false,
    loadError: null,
    login: vi.fn(),
    changePassword: vi.fn(),
    logout: vi.fn(),
    refreshStatus: vi.fn(),
  });
});

describe('App routing behavior', () => {
  it('shows loading fallback while auth status is initializing', () => {
    vi.mocked(AuthContext.useAuth).mockReturnValue({
      authEnabled: false,
      loggedIn: false,
      passwordSet: false,
      passwordChangeable: false,
      setupState: 'no_password',
      isLoading: true,
      loadError: null,
      login: vi.fn(),
      changePassword: vi.fn(),
      logout: vi.fn(),
      refreshStatus: vi.fn(),
    });

    const { container } = render(<App />);

    expect(container.querySelector('.border-t-cyan')).toBeTruthy();
  });

  it('redirects protected routes to login when auth is enabled but user not logged in', async () => {
    vi.mocked(AuthContext.useAuth).mockReturnValue({
      authEnabled: true,
      loggedIn: false,
      passwordSet: false,
      passwordChangeable: false,
      setupState: 'enabled',
      isLoading: false,
      loadError: null,
      login: vi.fn(),
      changePassword: vi.fn(),
      logout: vi.fn(),
      refreshStatus: vi.fn(),
    });
    window.history.pushState({}, '', '/portfolio');

    render(<App />);

    expect(await screen.findByTestId('login-page')).toBeInTheDocument();
  });

  it('renders route-level page components through lazy routes after auth is ready', async () => {
    window.history.pushState({}, '', '/chat');
    render(<App />);

    expect(await screen.findByTestId('chat-page')).toBeInTheDocument();
    expect(setCurrentRoute).toHaveBeenCalledWith('/chat');
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
    expect(screen.queryByTestId('home-page')).not.toBeInTheDocument();
  });
});
