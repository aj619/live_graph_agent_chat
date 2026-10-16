# Frontend image for Live Graph Agent Chat.
# Build context: frontend/ (compose/frontend.yml sets build.context accordingly).
# Multi-stage: Node builds the static Vite bundle, then nginx serves it.
# Tags pinned per SECURITY_CHECK.md's T1.12 record (checked 2026-10-16).

FROM node:24.22.0-trixie-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# VITE_APP_TITLE is the only build-time variable (plan §5.8) and is not a
# secret. Compose passes it from the repo .env as a build arg; this default
# covers a bare `docker build` with no arg. API_TOKEN is never read here.
ARG VITE_APP_TITLE="Live Graph Agent Chat"
ENV VITE_APP_TITLE=${VITE_APP_TITLE}
RUN npm run build

FROM nginx:1.30.6-alpine3.24

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8080
