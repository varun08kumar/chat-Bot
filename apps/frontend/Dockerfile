# syntax=docker/dockerfile:1
# Build the SPA, then serve it from nginx. Build context is apps/frontend.

FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
# Use a clean install when a lockfile is present, else a plain install.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:80/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
