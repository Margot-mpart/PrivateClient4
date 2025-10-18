# Frontend Dockerfile for PCC Platform
# Multi-stage build for optimal production image size

# =====================================================
# Stage 1: Build the React application
# =====================================================
FROM node:20-alpine AS build

# Set working directory
WORKDIR /app

# Copy package files and install dependencies
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

# Copy source code
COPY frontend/ ./

# Build arguments
ARG APP_ENV=production
ENV VITE_APP_ENV=${APP_ENV}

# Build the application
RUN npm run build

# =====================================================
# Stage 2: Production image
# =====================================================
FROM nginx:alpine

# Copy built assets from the build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Add health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q --spider http://localhost/ || exit 1

# Runtime environment variables
ARG APP_ENV=production
ENV APP_ENV=${APP_ENV}

# Create script to replace environment variables at runtime
RUN echo '#!/bin/sh' > /docker-entrypoint.d/40-replace-env-vars.sh && \
    echo 'set -e' >> /docker-entrypoint.d/40-replace-env-vars.sh && \
    echo 'envsubst "$(env | awk -F = \'{print "$"$1}\')" < /usr/share/nginx/html/assets/env-config.template.js > /usr/share/nginx/html/assets/env-config.js' >> /docker-entrypoint.d/40-replace-env-vars.sh && \
    chmod +x /docker-entrypoint.d/40-replace-env-vars.sh

# Expose port
EXPOSE 80

# No need to specify CMD as it's inherited from the nginx image
