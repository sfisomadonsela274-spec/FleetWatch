import dotenv from 'dotenv';
dotenv.config();

export const CONFIG = {
  PORT: process.env.NODE_PORT || (process.env.PORT && process.env.PORT !== '8080' ? process.env.PORT : 4000),
  HOST: process.env.NODE_HOST || '0.0.0.0',
  JWT_SECRET: process.env.JWT_SECRET || 'highveld_fleetwatch_jwt_secret_key_2026',
  DATABASE_URL: process.env.DATABASE_URL || 'postgresql://fleetwatch_admin:highveld_fleet_secret_2026@localhost:5432/fleetwatch',
  REDIS_URL: process.env.REDIS_URL || 'redis://localhost:6379',
  
  // South African Operational & Financial Constants
  ZAR_DIESEL_PRICE_PER_LITRE: 23.50,
  SANRAL_TOLL_FINE_ESTIMATE: 2500,
  UNAUTHORIZED_CARGO_RISK_ESTIMATE: 15000,
  SPEED_GOVERNOR_KMH_LIMIT: 80,
  RTMS_MAX_CONTINUOUS_DRIVE_MINS: 240, // 4 hours
  CORRIDOR_BUFFER_METERS: 150,

  // Free OSRM Routing Engine endpoint
  OSRM_ROUTER_URL: 'https://router.project-osrm.org'
};
