// Optional per-call authorization. When TENUO_TRUSTED_ROOT is set, every
// tools/call must carry a Tenuo warrant (in _meta.tenuo) that chains to that
// key, signed by the warrant's holder. Unset: no change.
import { createTenuo, TenuoError } from "@tenuo/core";

const rootHex = process.env.TENUO_TRUSTED_ROOT;
const tenuo = rootHex
  ? createTenuo({ trustedRoots: [createTenuo.publicKeyFromHex(rootHex)] })
  : undefined;

export type AuthzResult =
  | { ok: true; args: Record<string, any> }
  | { ok: false; message: string };

export async function authorizeToolCall(
  name: string,
  args: Record<string, any>,
  meta: unknown
): Promise<AuthzResult> {
  if (!tenuo) return { ok: true, args };
  try {
    const authorized = await tenuo.mcp.verify(name, args, meta, { allow: {} });
    return { ok: true, args: authorized as Record<string, any> };
  } catch (error) {
    const message =
      error instanceof TenuoError ? JSON.stringify(tenuo.mcp.jsonRpcError(error)) : "authorization failed";
    return { ok: false, message };
  }
}
