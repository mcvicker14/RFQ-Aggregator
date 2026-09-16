import { NextRequest } from "next/server";

/**
 * Proxies every /api/* request from the browser to the FastAPI backend.
 *
 * This replaces a next.config.js `rewrites()` rule that had the same intent but the
 * wrong mechanism for a containerized deploy: `rewrites()` is resolved once during
 * `next build` and its result is baked into `.next/routes-manifest.json` — verified
 * directly by building this app with BACKEND_URL unset and finding the literal
 * string "http://127.0.0.1:8000" written into that file. A Docker build stage does
 * not have the container's runtime environment variables (those are injected only
 * when the container starts), so the fallback got permanently baked in, and no
 * environment variable set afterward at runtime could change it — matching exactly
 * the ECONNREFUSED 127.0.0.1:8000 error seen in production.
 *
 * A route handler's function body, by contrast, runs fresh on every incoming
 * request, at real server runtime — so `resolveBackendUrl()` below always reflects
 * whatever BACKEND_URL the container actually has set right now.
 */

function resolveBackendUrl(): string {
  const configured = process.env.BACKEND_URL;
  if (configured) return configured;

  if (process.env.NODE_ENV === "production") {
    console.warn(
      "BACKEND_URL is not set. Falling back to http://127.0.0.1:8000, which only " +
      "exists in local development and will not work in this deployment. Set " +
      "BACKEND_URL in the hosting provider's environment variables for this service."
    );
  }
  return "http://127.0.0.1:8000";
}

// Headers that must not be forwarded as-is: they describe *this* hop (browser <->
// Next.js server) and would be wrong, or fetch() recomputes them itself.
const SKIP_REQUEST_HEADERS = new Set(["host", "connection", "content-length", "transfer-encoding", "keep-alive"]);
// content-encoding/transfer-encoding: fetch() already transparently decompresses the
// backend's response, so forwarding these would tell the browser to decompress
// already-decompressed bytes and corrupt the response.
const SKIP_RESPONSE_HEADERS = new Set(["content-encoding", "transfer-encoding", "connection", "keep-alive"]);

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const backendUrl = resolveBackendUrl();
  const targetUrl = `${backendUrl}/api/${path.join("/")}${request.nextUrl.search}`;

  const requestHeaders = new Headers();
  request.headers.forEach((value, key) => {
    if (!SKIP_REQUEST_HEADERS.has(key.toLowerCase())) requestHeaders.set(key, value);
  });

  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  let backendResponse: Response;
  try {
    backendResponse = await fetch(targetUrl, {
      method: request.method,
      headers: requestHeaders,
      // Streamed through untouched so large file uploads/downloads (documents,
      // solicitation PDFs) aren't buffered into memory and multipart boundaries
      // are never re-encoded.
      body: hasBody ? request.body : undefined,
      // Required by Node's fetch whenever `body` is a ReadableStream.
      ...(hasBody ? { duplex: "half" as const } : {}),
    });
  } catch (error) {
    console.error(`Failed to reach backend at ${targetUrl}:`, error);
    return Response.json(
      { detail: "Could not reach the backend service. It may be starting up — try again shortly." },
      { status: 502 }
    );
  }

  const responseHeaders = new Headers();
  backendResponse.headers.forEach((value, key) => {
    if (!SKIP_RESPONSE_HEADERS.has(key.toLowerCase())) responseHeaders.set(key, value);
  });

  return new Response(backendResponse.body, {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
    headers: responseHeaders,
  });
}

type RouteContext = { params: { path: string[] } };

export async function GET(request: NextRequest, { params }: RouteContext) {
  return proxy(request, params.path);
}
export async function POST(request: NextRequest, { params }: RouteContext) {
  return proxy(request, params.path);
}
export async function PATCH(request: NextRequest, { params }: RouteContext) {
  return proxy(request, params.path);
}
export async function DELETE(request: NextRequest, { params }: RouteContext) {
  return proxy(request, params.path);
}
