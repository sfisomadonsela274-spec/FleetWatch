import http from 'http';
import https from 'https';
import path from 'path';
import { fileURLToPath } from 'url';
import express from 'express';
import cors from 'cors';
import { Server as SocketIOServer } from 'socket.io';
import { CONFIG } from './config.js';
import authRoutes from './routes/auth.js';
import telemetryRoutes from './routes/telemetry.js';
import fleetRoutes from './routes/fleet.js';
import { store } from './db/store.js';
import { forwardToFastApi } from './services/proxy.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

const app = express();
const server = http.createServer(app);

// Enable CORS and JSON parsing
app.use(cors({ origin: '*' }));
app.use(express.json());

// Attach Socket.io
const io = new SocketIOServer(server, {
  cors: {
    origin: '*',
    methods: ['GET', 'POST']
  }
});
app.set('io', io);

// Serve static frontend files from workspace root
app.use(express.static(rootDir));

// Mount REST API routes
app.use('/api/v1/auth', authRoutes);
app.use('/api/v1/telemetry', telemetryRoutes);
app.use('/api/v1/fleet', fleetRoutes);

// Reverse proxy FastAPI routes (Reports, Email, SMS, Driver, Stream) to port 8001
app.use('/api/v1/reports', (req, res) => forwardToFastApi(req, res, `/api/v1/reports${req.url}`));
app.use('/api/v1/email', (req, res) => forwardToFastApi(req, res, `/api/v1/email${req.url}`));
app.use('/api/v1/sms', (req, res) => forwardToFastApi(req, res, `/api/v1/sms${req.url}`));
app.use('/api/v1/driver', (req, res) => forwardToFastApi(req, res, `/api/v1/driver${req.url}`));
app.use('/api/v1/stream', (req, res) => forwardToFastApi(req, res, `/api/v1/stream${req.url}`));

// Healthcheck endpoint
app.get('/api/health', (req, res) => {
  res.json({
    status: 'HEALTHY',
    service: 'FleetWatch South Africa Autonomous Telemetry Engine',
    version: '1.0.0',
    tenant: store.tenant.name,
    corridor: store.corridor.name,
    activeTrucks: store.getAllTrucks().length,
    activeAlerts: store.getAllAlerts().length,
    timestamp: new Date().toISOString()
  });
});

// Direct APK Download endpoint for driver mobile onboarding
app.get('/download/FleetSentinel-Driver.apk', (req, res) => {
  const apkPath = path.resolve(rootDir, 'mobile', 'FleetSentinel-Driver.apk');
  res.download(apkPath, 'FleetSentinel-Driver.apk');
});

// High-performance Open DEM terrain tile proxy (bypasses AWS S3 CORS restrictions for WebGL)
app.get('/api/terrain/:z/:x/:y.png', (req, res) => {
  const { z, x, y } = req.params;
  const targetUrl = `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/${z}/${x}/${y}.png`;

  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'public, max-age=86400');
  res.setHeader('Content-Type', 'image/png');

  const proxyReq = https.get(targetUrl, (tileRes) => {
    if (tileRes.statusCode !== 200) {
      return res.status(tileRes.statusCode).end();
    }
    tileRes.pipe(res);
  });
  proxyReq.on('error', () => {
    res.status(502).end();
  });
});

// Socket.io Real-Time Connection
io.on('connection', socket => {
  console.log(`[FleetWatch Socket.io] Terminal connected: ${socket.id}`);

  // Send initial fleet state immediately upon connection
  socket.emit('fleet:init', {
    trucks: store.getAllTrucks(),
    alerts: store.getAllAlerts(),
    corridor: store.getCorridor(),
    corridors: store.getAllCorridors(),
    waypointExceptions: store.getWaypointExceptions()
  });

  socket.on('disconnect', () => {
    console.log(`[FleetWatch Socket.io] Terminal disconnected: ${socket.id}`);
  });
});

// Start listening
server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    // Server daemon is already active on this port
    console.log(`[FleetWatch Server] Port ${CONFIG.PORT} already active, connecting test runner...`);
  } else {
    throw err;
  }
});

server.listen(CONFIG.PORT, CONFIG.HOST, () => {
  console.log(`
==================================================================
  🇿🇦 FLEETWATCH SOUTH AFRICA — AUTONOMOUS TELEMETRY ENGINE
==================================================================
  • REST API & UI:      http://localhost:${CONFIG.PORT}
  • Health Check:       http://localhost:${CONFIG.PORT}/api/health
  • Telemetry Ingress:  POST http://localhost:${CONFIG.PORT}/api/v1/telemetry/ping
  • Free GIS Engine:    PostGIS + Turf.js + OSRM (100% Free FOSS)
  • Primary Corridor:   N4 Highveld (Pretoria ⇄ Bronkhorstspruit ⇄ Witbank)
  • Waypoint Enforcer:  Rayton R515 Off-Ramp & Petroport Truck Stop
  • Anti-Siphoning:     Active (Acoustic & Negative Slope Sensing)
  • Multilingual SMS:   Active (isiZulu, Sesotho, English)
==================================================================
  `);
});

export { app, server, io };
