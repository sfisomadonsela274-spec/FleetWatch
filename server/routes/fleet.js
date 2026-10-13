import express from 'express';
import { z } from 'zod';
import { store } from '../db/store.js';
import { notificationService } from '../services/notifier.js';
import { routingService } from '../services/routing.js';
import { CONFIG } from '../config.js';
import { N4_JOURNEY_MULE } from '../db/journey_mule.js';
import { forwardToFastApi } from '../services/proxy.js';

const router = express.Router();

// Get High-Fidelity N4 Journey Mule Dataset
router.get('/journey-mule', (req, res) => {
  res.json({
    success: true,
    route: 'N4 Highveld Corridor (Pretoria East Depot ⇄ Witbank Central Terminal)',
    totalDistanceKm: N4_JOURNEY_MULE[N4_JOURNEY_MULE.length - 1].cumulativeKm,
    totalSteps: N4_JOURNEY_MULE.length,
    waypoints: N4_JOURNEY_MULE
  });
});

// Get all trucks
router.get('/trucks', (req, res) => {
  res.json({
    success: true,
    count: store.getAllTrucks().length,
    trucks: store.getAllTrucks()
  });
});

// Get single truck
router.get('/trucks/:id', (req, res) => {
  const truck = store.getTruckById(req.params.id);
  if (!truck) return res.status(404).json({ success: false, error: 'Truck not found' });
  res.json({ success: true, truck });
});

// Dispatch new truck
router.post('/trucks', (req, res) => {
  try {
    const schema = z.object({
      registration: z.string().min(4),
      model: z.string().optional(),
      trailer: z.string().optional(),
      driverName: z.string().min(2),
      driverPhone: z.string().min(9),
      driverLicense: z.string().optional()
    });

    const data = schema.parse(req.body);
    const newTruck = store.addTruck(data);

    // Emit event over WebSockets
    const io = req.app.get('io');
    if (io) {
      io.emit('fleet:truck_added', newTruck);
    }

    res.status(201).json({ success: true, truck: newTruck });
  } catch (err) {
    res.status(400).json({ success: false, error: err.errors || err.message });
  }
});

// Decommission / Offboard truck
router.delete('/trucks/:id', (req, res) => {
  const truckId = req.params.id;
  const deleted = store.deleteTruck(truckId);
  if (!deleted) {
    return res.status(404).json({ success: false, error: 'Truck not found' });
  }

  const io = req.app.get('io');
  if (io) {
    io.emit('fleet:truck_decommissioned', { truckId, truck: deleted });
  }

  res.json({
    success: true,
    truckId,
    message: `Truck ${deleted.registration} successfully decommissioned.`
  });
});

// Get alerts
router.get('/alerts', (req, res) => {
  res.json({
    success: true,
    count: store.getAllAlerts().length,
    alerts: store.getAllAlerts()
  });
});

// Resolve alert
router.post('/alerts/:id/resolve', (req, res) => {
  const resolved = store.resolveAlert(req.params.id);
  if (!resolved) return res.status(404).json({ success: false, error: 'Alert not found' });

  const io = req.app.get('io');
  if (io) {
    io.emit('fleet:alert_resolved', { alertId: req.params.id });
  }

  res.json({ success: true, alert: resolved });
});

// Clear resolved alerts
router.post('/alerts/clear-resolved', (req, res) => {
  const remaining = store.clearResolvedAlerts();
  const io = req.app.get('io');
  if (io) {
    io.emit('fleet:alerts_cleared');
  }
  res.json({ success: true, remainingCount: remaining.length });
});

// Get Corridor and Authorized Waypoint Exceptions
router.get('/corridors', (req, res) => {
  res.json({
    success: true,
    corridor: store.getCorridor(),
    corridors: store.getAllCorridors(),
    waypointExceptions: store.getWaypointExceptions(),
    tollPlazas: store.tollPlazas,
    unauthorizedDetours: store.unauthorizedDetours
  });
});

// Get specific corridor by ID
router.get('/corridors/:id', (req, res) => {
  const corridor = store.getCorridorById(req.params.id);
  if (!corridor) return res.status(404).json({ success: false, error: 'Corridor not found' });
  const exceptions = store.getWaypointExceptions(req.params.id);
  res.json({
    success: true,
    corridor,
    waypointExceptions: exceptions
  });
});

/**
 * Manager specifies a custom authorized route / off-ramp / truck stop
 * e.g. Rayton Off-ramp to Truck Stop and return to N4
 */
router.post('/corridors/exceptions', (req, res) => {
  try {
    const schema = z.object({
      name: z.string().min(3),
      description: z.string().optional(),
      offRampPoint: z.array(z.number()).length(2), // [lon, lat]
      onRampPoint: z.array(z.number()).length(2),  // [lon, lat]
      authorizedPolygon: z.array(z.array(z.number())).min(4), // [[lon, lat], ...]
      maxDwellMinutes: z.number().min(5).max(480).optional().default(45),
      allowedPurposes: z.array(z.string()).optional()
    });

    const data = schema.parse(req.body);
    const createdException = store.addWaypointException(data);

    const io = req.app.get('io');
    if (io) {
      io.emit('fleet:corridor_exception_added', createdException);
    }

    res.status(201).json({
      success: true,
      message: `Authorized waypoint exception '${createdException.name}' created successfully`,
      exception: createdException
    });
  } catch (err) {
    res.status(400).json({ success: false, error: err.errors || err.message });
  }
});

// Fetch driving route calculation using Free OSRM
router.post('/routes/calculate', async (req, res) => {
  try {
    const schema = z.object({
      coordinates: z.array(z.array(z.number())).min(2)
    });
    const data = schema.parse(req.body);
    const result = await routingService.getRoute(data.coordinates);
    res.json(result);
  } catch (err) {
    res.status(400).json({ success: false, error: err.message });
  }
});

// View outbound WhatsApp and SMS dispatch queue
router.get('/dispatches', (req, res) => {
  res.json({
    success: true,
    count: notificationService.getRecentDispatches().length,
    dispatches: notificationService.getRecentDispatches()
  });
});

// Pitch Meeting Simulator Triggers
router.post('/simulate/:type', async (req, res) => {
  const { type } = req.params;
  const truck = store.getTruckById('FW-01');

  if (!truck) return res.status(404).json({ success: false, error: 'Truck FW-01 not found' });

  let alert = null;
  if (type === 'siphon') {
    const litersLost = 75;
    truck.telemetry.fuelLevelLiters = Math.max(20, truck.telemetry.fuelLevelLiters - litersLost);
    alert = {
      id: `alert-sim-siphon-${Date.now()}`,
      truckId: truck.id,
      registration: truck.registration,
      type: 'FUEL_THEFT_CRITICAL',
      severity: 'CRITICAL',
      title: 'CRITICAL FUEL THEFT: Acoustic Tank Siphon Detected',
      description: `Immediate acoustic drop of ${litersLost}L detected while parked near Bronkhorstspruit.`,
      location: `${truck.telemetry.lat.toFixed(4)}, ${truck.telemetry.lng.toFixed(4)}`,
      financialImpactZAR: Math.round(litersLost * CONFIG.ZAR_DIESEL_PRICE_PER_LITRE),
      recommendedAction: 'Lock engine starter relay immediately & dispatch Armed Reaction unit.',
      timestamp: new Date().toISOString()
    };
  } else if (type === 'overspeed') {
    truck.telemetry.speed = 92;
    alert = {
      id: `alert-sim-speed-${Date.now()}`,
      truckId: truck.id,
      registration: truck.registration,
      type: 'SPEEDING_VIOLATION',
      severity: 'HIGH',
      title: 'Speed Governor Exceeded: 92 km/h (Limit: 80 km/h)',
      description: 'Truck traveling +12 km/h over heavy haulage limit on N4 East down Donkerhoek pass.',
      location: `${truck.telemetry.lat.toFixed(4)}, ${truck.telemetry.lng.toFixed(4)}`,
      financialImpactZAR: 2500,
      recommendedAction: 'Trigger in-cab acoustic speed buzzer & log AARTO demerit penalty.',
      timestamp: new Date().toISOString()
    };
  } else if (type === 'rayton-detour') {
    // Moves truck off N4 onto unauthorized Balmoral bypass
    truck.telemetry.lat = -25.8450;
    truck.telemetry.lng = 28.8950;
    alert = {
      id: `alert-sim-detour-${Date.now()}`,
      truckId: truck.id,
      registration: truck.registration,
      type: 'UNAUTHORIZED_TOLL_BYPASS',
      severity: 'CRITICAL',
      title: 'Unauthorized Toll Evasion Bypass: R104 Balmoral Dirt Bypass',
      description: 'Vehicle diverted onto unpaved R104 to avoid Diamond Hill SANRAL toll plaza.',
      location: '-25.8450, 28.8950',
      financialImpactZAR: 17500,
      recommendedAction: 'Lock remote accelerator via CAN-bus & notify Witbank corridor response.',
      timestamp: new Date().toISOString()
    };
  }

  if (alert) {
    store.addAlert(alert);
    await notificationService.sendDriverNotice(truck.driver, truck, alert, 'ZU');

    const io = req.app.get('io');
    if (io) {
      io.emit('fleet:alert_triggered', alert);
      io.emit('fleet:telemetry_updated', {
        truckId: truck.id,
        telemetry: truck.telemetry
      });
    }

    return res.json({ success: true, simulatedType: type, alert });
  }

  res.status(400).json({ success: false, error: 'Unknown simulation type' });
});

// SARS Diesel Refund Logbook Report
router.get('/reports/sars-diesel-logbook', (req, res) => {
  const trucks = store.getAllTrucks();
  const reportRows = trucks.map(t => {
    const totalHours = t.telemetry.engineHours || 500;
    const estimatedLiters = Math.round(totalHours * 18);
    const eligibleMiningOffRoadLiters = Math.round(estimatedLiters * 0.42); // 42% off-road at Witbank coal pits
    const rebateTariffPerLiterZAR = 3.65; // SARS Customs & Excise diesel rebate
    const estimatedRebateClaimZAR = Math.round(eligibleMiningOffRoadLiters * rebateTariffPerLiterZAR);

    return {
      truckId: t.id,
      registration: t.registration,
      model: t.model,
      engineHours: totalHours,
      totalFuelConsumedLiters: estimatedLiters,
      eligibleMiningOffRoadLiters,
      sarsRebateClaimZAR: estimatedRebateClaimZAR
    };
  });

  const totalRebateZAR = reportRows.reduce((sum, r) => sum + r.sarsRebateClaimZAR, 0);

  res.json({
    success: true,
    reportName: 'SARS Customs & Excise Diesel Rebate Schedule (Schedule 6)',
    taxYear: '2026',
    haulier: store.tenant.name,
    vatNumber: '4890214890',
    depot: store.tenant.depot,
    totalProjectedRebateZAR: totalRebateZAR,
    records: reportRows
  });
});

// Proxy FastAPI fleet units and driver dispatch endpoints through port 4000
router.get('/units', (req, res) => forwardToFastApi(req, res, req.originalUrl));
router.post('/dispatch', (req, res) => forwardToFastApi(req, res, req.originalUrl));
router.delete('/units/:id', (req, res) => forwardToFastApi(req, res, req.originalUrl));
router.post('/units/:id/decommission', (req, res) => forwardToFastApi(req, res, req.originalUrl));
router.post('/purge-demo', (req, res) => forwardToFastApi(req, res, req.originalUrl));
router.post('/provision', (req, res) => forwardToFastApi(req, res, req.originalUrl));

export default router;
