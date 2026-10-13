import { SEED_DATA } from './seed.js';

class FleetWatchStore {
  constructor() {
    this.tenant = { ...SEED_DATA.tenant };
    this.user = { ...SEED_DATA.user };
    this.corridor = { ...SEED_DATA.corridor };
    this.corridors = [...(SEED_DATA.corridors || [SEED_DATA.corridor])];
    this.waypointExceptions = [...SEED_DATA.waypointExceptions];
    this.tollPlazas = [...SEED_DATA.tollPlazas];
    this.unauthorizedDetours = [...SEED_DATA.unauthorizedDetours];
    
    // Map of trucks indexed by ID
    this.trucks = new Map();
    SEED_DATA.trucks.forEach(t => {
      this.trucks.set(t.id, JSON.parse(JSON.stringify(t)));
    });

    // Active & historical alerts
    this.alerts = [
      {
        id: 'alert-init-1',
        truckId: 'FW-01',
        registration: 'WP 889 GP',
        type: 'SPEEDING_VIOLATION',
        severity: 'HIGH',
        title: 'Speed Governor Exceeded: 84 km/h (Limit: 80 km/h)',
        description: 'Class 3 statutory highway speed cap exceeded on N4 East near Donkerhoek.',
        location: '-25.7520, 28.4350',
        financialImpactZAR: 2500,
        recommendedAction: 'Trigger in-cab speed buzzer & log AARTO demerit record.',
        timestamp: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
        status: 'ACTIVE'
      },
      {
        id: 'alert-init-2',
        truckId: 'FW-03',
        registration: 'KZ 901 GP',
        type: 'RTMS_FATIGUE_BREACH',
        severity: 'WARNING',
        title: 'RTMS Fatigue Ceiling: 4.1h Continuous Driving',
        description: 'Driver Bongani Sithole has exceeded the 4-hour statutory driving block.',
        location: '-25.8620, 29.0980',
        financialImpactZAR: 3500,
        recommendedAction: 'Instruct driver to rest 15 mins at Clewer lay-by.',
        timestamp: new Date(Date.now() - 40 * 60 * 1000).toISOString(),
        status: 'ACTIVE'
      }
    ];

    // Outbound notifications history
    this.dispatches = [];
  }

  // Trucks
  getAllTrucks() {
    return Array.from(this.trucks.values());
  }

  getTruckById(id) {
    return this.trucks.get(id) || null;
  }

  updateTruckTelemetry(id, newTelemetry) {
    const truck = this.trucks.get(id);
    if (!truck) return null;
    truck.telemetry = { ...truck.telemetry, ...newTelemetry };
    return truck;
  }

  addTruck(truckData) {
    const id = truckData.id || `FW-0${this.trucks.size + 1}`;
    const newTruck = {
      id,
      registration: truckData.registration,
      vin: truckData.vin || `VIN${Date.now()}`,
      model: truckData.model || 'Scania R500',
      trailer: truckData.trailer || 'Side-Tipper 34T',
      driver: {
        name: truckData.driverName || 'New Driver',
        phone: truckData.driverPhone || '+27 82 000 0000',
        license: truckData.driverLicense || 'Code 14 (EC)'
      },
      telemetry: {
        lat: truckData.lat || -25.7620,
        lng: truckData.lng || 28.5280,
        heading: 90,
        speed: 0,
        fuelLevelLiters: 450,
        fuelCapacityLiters: 650,
        fuelBurnRate: 35.0,
        engineHours: 100,
        idleMinutes: 0,
        continuousDriveMinutes: 0,
        batteryPercent: 100,
        isCharging: true,
        pwaActive: true,
        status: 'EN_ROUTE',
        currentZone: 'Depot Ready'
      }
    };
    this.trucks.set(id, newTruck);
    return newTruck;
  }

  deleteTruck(id) {
    const truck = this.trucks.get(id);
    if (truck) {
      this.trucks.delete(id);
      return truck;
    }
    return null;
  }

  // Alerts
  getAllAlerts() {
    return this.alerts;
  }

  addAlert(alert) {
    this.alerts.unshift({ ...alert, status: 'ACTIVE' });
    if (this.alerts.length > 50) this.alerts.pop();
    return alert;
  }

  resolveAlert(alertId) {
    const alert = this.alerts.find(a => a.id === alertId);
    if (alert) {
      alert.status = 'RESOLVED';
      alert.resolvedAt = new Date().toISOString();
      return alert;
    }
    return null;
  }

  clearResolvedAlerts() {
    this.alerts = this.alerts.filter(a => a.status !== 'RESOLVED');
    return this.alerts;
  }

  // Corridors and Manager Waypoint Exceptions
  getCorridor() {
    return this.corridor;
  }

  getAllCorridors() {
    return this.corridors;
  }

  getCorridorById(id) {
    return this.corridors.find(c => c.id === id) || (this.corridor.id === id ? this.corridor : null);
  }

  getWaypointExceptions(corridorId = null) {
    if (!corridorId) return this.waypointExceptions;
    return this.waypointExceptions.filter(e => e.corridorId === corridorId);
  }

  /**
   * Allows the truck manager to define a new authorized route / off-ramp / truck stop
   */
  addWaypointException(exceptionData) {
    const newException = {
      id: exceptionData.id || `exc-${Date.now()}`,
      tenantId: this.tenant.id,
      corridorId: this.corridor.id,
      name: exceptionData.name, // e.g. "Rayton R515 Off-Ramp & Petroport"
      description: exceptionData.description || 'Manager authorized route exception',
      offRampPoint: exceptionData.offRampPoint, // [lon, lat]
      onRampPoint: exceptionData.onRampPoint,   // [lon, lat]
      authorizedPolygon: exceptionData.authorizedPolygon, // [[lon, lat], ...]
      maxDwellMinutes: exceptionData.maxDwellMinutes || 45,
      allowedPurposes: exceptionData.allowedPurposes || ['FUEL', 'RTMS_REST']
    };
    this.waypointExceptions.push(newException);
    return newException;
  }
}

export const store = new FleetWatchStore();
