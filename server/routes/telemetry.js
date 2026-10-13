import express from 'express';
import { z } from 'zod';
import { store } from '../db/store.js';
import { rulesEngine } from '../engine/rules.js';
import { notificationService } from '../services/notifier.js';

const router = express.Router();

const TelemetryPingSchema = z.object({
  truckId: z.string(),
  lat: z.number().min(-35).max(-20),
  lng: z.number().min(15).max(35),
  heading: z.number().optional().default(90),
  speed: z.number().min(0).max(160),
  fuelLevelLiters: z.number().min(0),
  batteryPercent: z.number().min(0).max(100).optional().default(90),
  isCharging: z.boolean().optional().default(true),
  pwaActive: z.boolean().optional().default(true),
  dwellMinutesAtStop: z.number().optional().default(0)
});

// Telemetry Ping Ingestion
router.post('/ping', async (req, res) => {
  try {
    const ping = TelemetryPingSchema.parse(req.body);
    const truck = store.getTruckById(ping.truckId);

    if (!truck) {
      return res.status(404).json({ success: false, error: `Truck ${ping.truckId} not found` });
    }

    const previousFuel = truck.telemetry.fuelLevelLiters;
    const previousContinuousMinutes = truck.telemetry.continuousDriveMinutes || 0;
    const newContinuousMinutes = ping.speed > 10 ? previousContinuousMinutes + 1 : Math.max(0, previousContinuousMinutes - 2);

    // 1. Evaluate Corridor Compliance (N4 vs Rayton Waypoint vs Detour)
    const corridorEval = rulesEngine.checkCorridorCompliance(
      truck,
      ping.lat,
      ping.lng,
      ping.dwellMinutesAtStop
    );

    // 2. Evaluate Anti-Siphon
    const siphonAlert = rulesEngine.checkFuelSiphon(truck, ping.fuelLevelLiters, previousFuel, 30);

    // 3. Evaluate Speed Governor
    const speedAlert = rulesEngine.checkSpeedCompliance(truck, ping.speed);

    // 4. Evaluate RTMS Rest
    const rtmsAlert = rulesEngine.checkRtmsCompliance(truck, newContinuousMinutes);

    // 5. Evaluate Phone Integrity
    const phoneAlert = rulesEngine.checkDriverPhoneCompliance(
      truck,
      ping.batteryPercent,
      ping.isCharging,
      ping.speed > 15
    );

    // Collect all new alerts
    const generatedAlerts = [corridorEval.alert, siphonAlert, speedAlert, rtmsAlert, phoneAlert].filter(Boolean);

    // Update truck state
    const updatedTruck = store.updateTruckTelemetry(ping.truckId, {
      lat: ping.lat,
      lng: ping.lng,
      heading: ping.heading,
      speed: ping.speed,
      fuelLevelLiters: ping.fuelLevelLiters,
      continuousDriveMinutes: newContinuousMinutes,
      batteryPercent: ping.batteryPercent,
      isCharging: ping.isCharging,
      pwaActive: ping.pwaActive,
      status: ping.speed === 0 ? 'RESTING' : 'EN_ROUTE',
      currentZone: corridorEval.zone
    });

    // Save alerts and trigger notifications
    for (const alert of generatedAlerts) {
      store.addAlert(alert);
      
      // Dispatch WhatsApp notice in isiZulu
      await notificationService.sendDriverNotice(truck.driver, truck, alert, 'ZU');

      // Real-time broadcast to connected CEO and manager terminals
      const io = req.app.get('io');
      if (io) {
        io.emit('fleet:alert_triggered', alert);
      }
    }

    // Broadcast updated truck telemetry over WebSockets
    const io = req.app.get('io');
    if (io) {
      io.emit('fleet:telemetry_updated', {
        truckId: ping.truckId,
        telemetry: updatedTruck.telemetry,
        zone: corridorEval.zone,
        status: corridorEval.status
      });
    }

    return res.json({
      success: true,
      truckId: ping.truckId,
      corridorStatus: corridorEval.status,
      zone: corridorEval.zone,
      distanceFromCorridorMeters: corridorEval.distanceMeters,
      alertsTriggered: generatedAlerts.length,
      alerts: generatedAlerts
    });
  } catch (err) {
    return res.status(400).json({ success: false, error: err.errors || err.message });
  }
});

export default router;
