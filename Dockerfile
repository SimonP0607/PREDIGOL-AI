# PrediGol web for a server: the TanStack Start app built for Node (Nitro preset node-server) and served
# behind the reverse proxy, on the same origin as the API (the proxy sends /api/v1 to the API).
#
#   docker build --build-arg VITE_API_BASE_URL=https://predigol.example --build-arg VITE_APP_VERSION=$(git rev-parse --short=12 HEAD) -t predigol-web .
#
# No secret goes in: VITE_* values end up in the browser bundle and are public by nature. VITE_API_BASE_URL only
# switches the app to live data; the browser always calls its own origin.
FROM oven/bun:1.3.13-alpine AS build
WORKDIR /app
COPY package.json bun.lock bunfig.toml ./
RUN bun install --frozen-lockfile
COPY . .
ARG VITE_API_BASE_URL
ARG VITE_APP_VERSION=unknown
ENV NITRO_PRESET=node-server \
    VITE_DATA_MODE=live \
    VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_APP_VERSION=${VITE_APP_VERSION}
RUN test -n "$VITE_API_BASE_URL" || { echo "VITE_API_BASE_URL is required (the public https:// origin)"; exit 1; }
RUN bun run build && test -f .output/server/index.mjs && test -f .output/public/sw.js

FROM node:22-alpine
ENV NODE_ENV=production HOST=0.0.0.0 PORT=3000
WORKDIR /app
COPY --from=build --chown=node:node /app/.output ./.output
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:3000/login || exit 1
CMD ["node", ".output/server/index.mjs"]
