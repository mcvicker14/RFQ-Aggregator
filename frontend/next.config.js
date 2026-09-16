/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // /api/* is proxied to the backend by src/app/api/[...path]/route.ts, a Route
  // Handler — deliberately NOT a rewrites() rule here. rewrites() is resolved once
  // at `next build` time and its result is baked into the build output, so it can
  // never see a container's runtime environment variables (this broke production:
  // BACKEND_URL was set correctly at deploy time but the build-time-baked
  // 127.0.0.1:8000 fallback was what actually shipped). A Route Handler runs fresh
  // per request, at real server runtime, so it always sees the current BACKEND_URL.
};

module.exports = nextConfig;
