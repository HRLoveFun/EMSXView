# ==============================================================
# EMSXView Frontend – Multi-stage Production Docker Build
# Stage 1: Build React/Vite app
# Stage 2: Serve via Nginx
# ==============================================================

# ---- Build Stage ----
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first (cache-friendly layer)
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline

# Copy source and build
COPY . .

# VITE_API_URL is intentionally left empty at build time.
# At runtime Nginx proxies /api/* to the backend container,
# so the frontend calls relative /api/... paths.
RUN npm run build

# ---- Production Stage ----
FROM nginx:1.27-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Nginx config is injected via docker-compose volume mount
# (emsxview-backend/config/nginx.conf → /etc/nginx/conf.d/default.conf)

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
