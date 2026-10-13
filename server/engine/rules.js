import * as turf from '@turf/turf';
import { CONFIG } from '../config.js';
import { SEED_DATA } from '../db/seed.js';

export class ComplianceRulesEngine {
  constructor() {
    this.corridorLine = turf.lineString(SEED_DATA.corridor.routeCoordinates);
    this.waypointExceptions = SEED_DATA.waypointExceptions;
    this.tollPlazas = SEED_DATA.tollPlazas;
    this.unauthorizedDetours = SEED_DATA.unauthorizedDetours;
  }

  /**
   * Evaluates vehicle location against N4 corridor and Rayton authorized off-ramp/truck stop
   */
  checkCorridorCompliance(truck, lat, lng, dwellMinutesAtStop = 0) {
    const pt = turf.point([lng, lat]);
    
    // 1. Calculate distance to primary N4 corridor line in meters
    const distanceKm = turf.pointToLineDistance(pt, this.corridorLine, { units: 'kilometers' });
    const distanceMeters = distanceKm * 1000;

    // 2. Check if vehicle is within an authorized waypoint exception facility (e.g. Rayton Off-ramp & Truck Stop)
    for (const exc of this.waypointExceptions) {
      const polygon = turf.polygon([exc.authorizedPolygon]);
      const isInsideAuthorizedStop = turf.booleanPointInPolygon(pt, polygon);
      const offRampDist = turf.distance(pt, turf.point(exc.offRampPoint), { units: 'kilometers' }) * 1000;

      if (isInsideAuthorizedStop || offRampDist <= 250) {
        // Vehicle is at authorized off-ramp / truck stop!
        if (dwellMinutesAtStop > exc.maxDwellMinutes) {
          return {
            status: 'EXCESSIVE_DWELL',
            zone: exc.name,
            distanceMeters: Math.round(distanceMeters),
            alert: {
              id: `alert-dwell-${truck.id}-${Date.now()}`,
              truckId: truck.id,
              registration: truck.registration,
              type: 'EXCESSIVE_DWELL',
              severity: 'WARNING',
              title: `Excessive Dwell at ${exc.name}`,
              description: `Truck ${truck.registration} has spent ${dwellMinutesAtStop}m at ${exc.name} (limit: ${exc.maxDwellMinutes}m).`,
              location: `${lat.toFixed(4)}, ${lng.toFixed(4)}`,
              financialImpactZAR: 450,
              recommendedAction: 'Contact driver via WhatsApp to prompt corridor departure.',
              timestamp: new Date().toISOString()
            }
          };
        }

        return {
          status: 'AUTHORIZED_WAYPOINT',
          zone: `${exc.name} (Authorized Refuel/Rest)`,
          distanceMeters: Math.round(distanceMeters),
          alert: null
        };
      }
    }

    // 3. Inside primary highway buffer
    if (distanceMeters <= (SEED_DATA.corridor.bufferMeters || CONFIG.CORRIDOR_BUFFER_METERS)) {
      return {
        status: 'CORRIDOR_COMPLIANT',
        zone: 'N4 Highveld Mainline',
        distanceMeters: Math.round(distanceMeters),
        alert: null
      };
    }

    // 3. Check if near known unauthorized dirt bypasses (e.g. R104 Balmoral toll avoidance)
    for (const detour of this.unauthorizedDetours) {
      const detourDist = turf.distance(pt, turf.point(detour.center), { units: 'kilometers' }) * 1000;
      if (detourDist <= detour.radiusMeters) {
        return {
          status: 'UNAUTHORIZED_DETOUR',
          zone: detour.name,
          distanceMeters: Math.round(distanceMeters),
          alert: {
            id: `alert-detour-${truck.id}-${Date.now()}`,
            truckId: truck.id,
            registration: truck.registration,
            type: 'UNAUTHORIZED_TOLL_BYPASS',
            severity: 'CRITICAL',
            title: `Unauthorized Toll Evasion Bypass Detected: ${detour.name}`,
            description: `Truck ${truck.registration} diverted off the N4 onto gravel bypass ${detour.name}. Cargo exposed to high-jack corridor.`,
            location: `${lat.toFixed(4)}, ${lng.toFixed(4)}`,
            financialImpactZAR: detour.riskZAR,
            recommendedAction: 'Lock remote accelerator via CAN-bus & notify Witbank corridor response.',
            timestamp: new Date().toISOString()
          }
        };
      }
    }

    // 4. General unauthorized deviation
    return {
      status: 'UNAUTHORIZED_DEVIATION',
      zone: 'Off-Corridor Unpaved / Unapproved Route',
      distanceMeters: Math.round(distanceMeters),
      alert: {
        id: `alert-dev-${truck.id}-${Date.now()}`,
        truckId: truck.id,
        registration: truck.registration,
        type: 'CORRIDOR_BREACH',
        severity: 'HIGH',
        title: `Corridor Boundary Breach (${Math.round(distanceMeters)}m from N4)`,
        description: `Vehicle left the geofenced N4 Highveld corridor at an unauthorized exit point.`,
        location: `${lat.toFixed(4)}, ${lng.toFixed(4)}`,
        financialImpactZAR: CONFIG.SANRAL_TOLL_FINE_ESTIMATE + 5000,
        recommendedAction: 'Dispatch immediate check-in WhatsApp and inspect GPS signal fidelity.',
        timestamp: new Date().toISOString()
      }
    };
  }

  /**
   * Detects sudden fuel loss (Siphoning)
   */
  checkFuelSiphon(truck, currentLiters, previousLiters, elapsedSeconds = 60) {
    if (previousLiters === undefined || previousLiters === null) return null;
    
    const litersLost = previousLiters - currentLiters;

    // If more than 15L lost in under 120 seconds
    if (litersLost >= 15 && elapsedSeconds <= 120) {
      const estimatedCost = Math.round(litersLost * CONFIG.ZAR_DIESEL_PRICE_PER_LITRE);
      return {
        id: `alert-siphon-${truck.id}-${Date.now()}`,
        truckId: truck.id,
        registration: truck.registration,
        type: 'FUEL_THEFT_CRITICAL',
        severity: 'CRITICAL',
        title: `CRITICAL FUEL THEFT: Acoustic Tank Siphon Detected`,
        description: `Sudden acoustic resonance drop of ${litersLost.toFixed(1)}L detected in ${elapsedSeconds}s while stationary.`,
        location: `${truck.telemetry.lat.toFixed(4)}, ${truck.telemetry.lng.toFixed(4)}`,
        financialImpactZAR: estimatedCost,
        recommendedAction: 'Lock engine starter relay immediately & dispatch Armed Reaction unit.',
        timestamp: new Date().toISOString()
      };
    }
    return null;
  }

  /**
   * Checks Class 3 heavy vehicle 80 km/h statutory speed limit
   */
  checkSpeedCompliance(truck, speedKmh) {
    if (speedKmh > CONFIG.SPEED_GOVERNOR_KMH_LIMIT) {
      const overspeed = speedKmh - CONFIG.SPEED_GOVERNOR_KMH_LIMIT;
      return {
        id: `alert-speed-${truck.id}-${Date.now()}`,
        truckId: truck.id,
        registration: truck.registration,
        type: 'SPEEDING_VIOLATION',
        severity: 'HIGH',
        title: `Speed Governor Exceeded: ${speedKmh} km/h (Limit: ${CONFIG.SPEED_GOVERNOR_KMH_LIMIT} km/h)`,
        description: `Vehicle traveling +${overspeed} km/h over the Class 3 heavy haulage statutory limit on national road.`,
        location: `${truck.telemetry.lat.toFixed(4)}, ${truck.telemetry.lng.toFixed(4)}`,
        financialImpactZAR: 2500,
        recommendedAction: 'Trigger in-cab acoustic speed warning & log AARTO demerit penalty.',
        timestamp: new Date().toISOString()
      };
    }
    return null;
  }

  /**
   * Checks continuous driving fatigue against RTMS 4.0-hour statutory limit
   */
  checkRtmsCompliance(truck, continuousDriveMinutes) {
    if (continuousDriveMinutes >= CONFIG.RTMS_MAX_CONTINUOUS_DRIVE_MINS) {
      const hours = (continuousDriveMinutes / 60).toFixed(1);
      return {
        id: `alert-rtms-${truck.id}-${Date.now()}`,
        truckId: truck.id,
        registration: truck.registration,
        type: 'RTMS_FATIGUE_BREACH',
        severity: 'WARNING',
        title: `RTMS Rest Breach: ${hours} hrs Continuous Driving`,
        description: `Driver ${truck.driver.name} has exceeded the 4-hour statutory driving ceiling without verified rest.`,
        location: `${truck.telemetry.lat.toFixed(4)}, ${truck.telemetry.lng.toFixed(4)}`,
        financialImpactZAR: 3500,
        recommendedAction: 'Instruct driver to pull into Rayton or Bronkhorstspruit Petroport for mandatory 15m rest.',
        timestamp: new Date().toISOString()
      };
    }
    return null;
  }

  /**
   * Checks driver mobile phone health in transit
   */
  checkDriverPhoneCompliance(truck, batteryPercent, isCharging, isMoving) {
    if (isMoving && batteryPercent < 15 && !isCharging) {
      return {
        id: `alert-phone-${truck.id}-${Date.now()}`,
        truckId: truck.id,
        registration: truck.registration,
        type: 'DRIVER_PHONE_CRITICAL',
        severity: 'WARNING',
        title: `Driver Device Critical Battery: ${batteryPercent}%`,
        description: `Driver mobile device is uncharged while vehicle is in transit on N4. Risk of tracking loss.`,
        location: `${truck.telemetry.lat.toFixed(4)}, ${truck.telemetry.lng.toFixed(4)}`,
        financialImpactZAR: 850,
        recommendedAction: 'Dispatch high-priority vibration ping to driver handset.',
        timestamp: new Date().toISOString()
      };
    }
    return null;
  }
}

export const rulesEngine = new ComplianceRulesEngine();
