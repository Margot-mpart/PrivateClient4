/**
 * PCC Platform - Runtime Environment Configuration
 * 
 * This file is processed at container startup to inject environment variables.
 * Variables are replaced using the ${VARIABLE_NAME} syntax.
 * 
 * DO NOT MODIFY THIS FILE DIRECTLY - changes will be overwritten.
 * The processed version will be available as env-config.js
 */

window.ENV = {
  // Core environment
  APP_ENV: '${APP_ENV}',
  
  // API configuration
  API_URL: '${API_URL}',
  
  // Feature flags
  ENABLE_AI_FEATURES: ${ENABLE_AI_FEATURES:-true},
  MAINTENANCE_MODE: ${MAINTENANCE_MODE:-false},
  
  // Integrations
  STRIPE_PUBLISHABLE_KEY: '${STRIPE_PUBLISHABLE_KEY}',
  DAILY_API_KEY: '${DAILY_API_KEY}',
  
  // Monitoring
  SENTRY_DSN: '${SENTRY_DSN:-}',
  ENABLE_TELEMETRY: ${ENABLE_TELEMETRY:-true},
  
  // Build information
  BUILD_VERSION: '${BUILD_VERSION:-dev}',
  BUILD_TIMESTAMP: '${BUILD_TIMESTAMP:-}',
  
  // Generated at runtime
  DEPLOYED_AT: new Date().toISOString()
};

console.log('[PCC Platform] Environment loaded:', window.ENV.APP_ENV);
