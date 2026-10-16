import { UserManager, WebStorageStateStore } from "oidc-client-ts";
import type { AppConfig } from "./types";

const managers = new Map<string, UserManager>();
let callbackTask: Promise<void> | null = null;

export function createUserManager(config: AppConfig): UserManager {
  const key = [
    config.region,
    config.userPoolId,
    config.clientId,
    config.redirectUri,
  ].join("|");
  const existing = managers.get(key);
  if (existing) return existing;

  const store = new WebStorageStateStore({ store: window.sessionStorage });
  const manager = new UserManager({
    authority: `https://cognito-idp.${config.region}.amazonaws.com/${config.userPoolId}`,
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    response_type: "code",
    response_mode: "query",
    scope: "openid email profile",
    // Authorization code uses S256 PKCE unless disablePKCE is set.
    disablePKCE: false,
    loadUserInfo: false,
    automaticSilentRenew: false,
    monitorSession: false,
    userStore: store,
    stateStore: store,
  });
  managers.set(key, manager);
  return manager;
}

export function readAuthError(): string | null {
  const params = new URLSearchParams(window.location.search);
  if (params.has("code") || !params.has("error")) return null;
  const description = params.get("error_description");
  const code = params.get("error");
  return `A entrada falhou. ${description || code || "Tente novamente."}`;
}

export function completeSignIn(manager: UserManager): Promise<void> {
  const params = new URLSearchParams(window.location.search);
  if (!(params.has("code") && params.has("state"))) return Promise.resolve();
  if (!callbackTask) {
    callbackTask = manager
      .signinRedirectCallback()
      .then(() => {
        const url = new URL(window.location.href);
        url.searchParams.delete("code");
        url.searchParams.delete("state");
        url.searchParams.delete("session_state");
        const next = `${url.pathname}${url.search}${url.hash}` || "/";
        window.history.replaceState({}, "", next);
      })
      .catch((error: unknown) => {
        callbackTask = null;
        throw error;
      });
  }
  return callbackTask;
}

export async function idToken(manager: UserManager): Promise<string | null> {
  const user = await manager.getUser();
  if (!user || user.expired) return null;
  return user.id_token ?? null;
}

export async function logout(config: AppConfig, manager: UserManager): Promise<void> {
  await manager.removeUser();
  const domain = config.cognitoDomain.replace(/\/$/, "");
  const url = `${domain}/logout?client_id=${encodeURIComponent(config.clientId)}&logout_uri=${encodeURIComponent(config.redirectUri)}`;
  window.location.assign(url);
}
