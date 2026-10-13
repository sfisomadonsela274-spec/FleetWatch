import { CONFIG } from '../config.js';

export class FreeOsrmRoutingService {
  constructor(baseUrl = CONFIG.OSRM_ROUTER_URL) {
    this.baseUrl = baseUrl;
  }

  /**
   * Fetches driving route between waypoints using free OSRM engine
   * @param {Array<[lon, lat]>} coordinates - Array of [lon, lat] pairs
   */
  async getRoute(coordinates) {
    try {
      const coordString = coordinates.map(c => `${c[0]},${c[1]}`).join(';');
      const url = `${this.baseUrl}/route/v1/driving/${coordString}?overview=full&geometries=geojson&steps=false`;
      
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 4000);

      const response = await fetch(url, { signal: controller.signal });
      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`OSRM responded with status ${response.status}`);
      }

      const data = await response.json();
      if (data.code === 'Ok' && data.routes && data.routes.length > 0) {
        const route = data.routes[0];
        return {
          success: true,
          source: 'OSRM_ONLINE',
          distanceKm: Number((route.distance / 1000).toFixed(2)),
          durationMinutes: Math.round(route.duration / 60),
          geometry: route.geometry.coordinates // Array of [lon, lat]
        };
      }
      throw new Error('No route found in OSRM payload');
    } catch (err) {
      // Fallback offline calculation using straight line + road tortuosity factor (1.25)
      console.warn(`[OSRM Routing Fallback] Network request bypassed: ${err.message}. Using offline interpolation.`);
      return this.calculateOfflineRoute(coordinates);
    }
  }

  /**
   * Offline mathematical route fallback
   */
  calculateOfflineRoute(coordinates) {
    let totalDistKm = 0;
    for (let i = 0; i < coordinates.length - 1; i++) {
      const [lon1, lat1] = coordinates[i];
      const [lon2, lat2] = coordinates[i + 1];
      totalDistKm += this.haversineDistance(lat1, lon1, lat2, lon2) * 1.22; // 22% road curve factor
    }

    return {
      success: true,
      source: 'OFFLINE_MATH_FALLBACK',
      distanceKm: Number(totalDistKm.toFixed(2)),
      durationMinutes: Math.round((totalDistKm / 75) * 60), // Assuming 75 km/h average speed
      geometry: coordinates
    };
  }

  haversineDistance(lat1, lon1, lat2, lon2) {
    const toRad = x => (x * Math.PI) / 180;
    const R = 6371; // Earth radius in km
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }
}

export const routingService = new FreeOsrmRoutingService();
