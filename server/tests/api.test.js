import { CONFIG } from '../config.js';
import { server } from '../index.js';

async function runTests() {
  console.log('--- STARTING FLEETWATCH BACKEND INTEGRATION TESTS ---');
  let testsPassed = 0;
  const baseUrl = `http://localhost:${CONFIG.PORT}`;

  try {
    // Wait briefly for server startup
    await new Promise(r => setTimeout(r, 600));

    // Test 1: Healthcheck
    console.log('\n[Test 1] Healthcheck endpoint');
    const healthRes = await fetch(`${baseUrl}/api/health`);
    const healthData = await healthRes.json();
    if (healthData.status === 'HEALTHY' && healthData.activeTrucks > 0) {
      console.log('✅ Healthcheck passed! Active trucks:', healthData.activeTrucks);
      testsPassed++;
    } else {
      throw new Error('Healthcheck failed');
    }

    // Test 2: CEO Demo Login & JWT
    console.log('\n[Test 2] CEO Demo Login & Token Verification');
    const authRes = await fetch(`${baseUrl}/api/v1/auth/ceo-demo`, { method: 'POST' });
    const authData = await authRes.json();
    if (!authData.success || !authData.token) throw new Error('Auth failed');
    const token = authData.token;
    console.log('✅ CEO Demo Login passed! User:', authData.user.name, '| Role:', authData.user.role);
    testsPassed++;

    const meRes = await fetch(`${baseUrl}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    const meData = await meRes.json();
    if (!meData.success || meData.user.name !== 'Thabo Motsepe') throw new Error('Token verification failed');
    console.log('✅ JWT Token verification passed! Tenant:', meData.tenant.name);
    testsPassed++;

    // Test 3: Fetch Corridors, 1-to-1 Vehicle Linkage & Permitted Divergence Points
    console.log('\n[Test 3] Corridors & 1-to-1 Vehicle Linkage & Permitted Divergence Points');
    const corridorRes = await fetch(`${baseUrl}/api/v1/fleet/corridors`);
    const corridorData = await corridorRes.json();
    if (!corridorData.corridors || corridorData.corridors.length < 3) throw new Error('Expected multiple corridors');
    const n4Corridor = corridorData.corridors.find(c => c.id === 'corridor-n4-highveld');
    if (!n4Corridor || n4Corridor.assignedTruckId !== 'FW-01') throw new Error('1-to-1 linkage between corridor and truck FW-01 failed');
    console.log('✅ 1-to-1 Corridor-to-Vehicle Linkage verified:', `${n4Corridor.name} ⇄ ${n4Corridor.assignedTruckId}`);

    const raytonException = corridorData.waypointExceptions.find(e => e.id === 'exc-rayton-truckstop');
    if (!raytonException) throw new Error('Rayton waypoint exception not found in seed');
    console.log('✅ Permitted Divergence Point verified! Found authorized off-ramp:', raytonException.name);
    console.log('   KM Marker:', raytonException.kmMarker, '| Max Dwell:', raytonException.maxDwellMinutes, 'mins | Off-ramp:', raytonException.offRampPoint);
    testsPassed++;

    // Test 3B: Single Corridor Lookup API
    const singleCorridorRes = await fetch(`${baseUrl}/api/v1/fleet/corridors/corridor-n4-highveld`);
    const singleCorridorData = await singleCorridorRes.json();
    if (!singleCorridorData.success || singleCorridorData.corridor.assignedTruckId !== 'FW-01') {
      throw new Error('Single corridor lookup failed');
    }
    console.log('✅ Single corridor lookup passed! Verified route coordinates:', singleCorridorData.corridor.routeCoordinates.length);
    testsPassed++;

    // Test 4: Manager Adds a New Custom Route Exception (User feature request)
    console.log('\n[Test 4] Manager Custom Waypoint Exception Specification');
    const newExcRes = await fetch(`${baseUrl}/api/v1/fleet/corridors/exceptions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: 'Bronkhorstspruit Agricultural Silo Depot Spur',
        description: 'Authorized 30m spur for grain weighbridge inspection',
        offRampPoint: [28.7420, -25.8050],
        onRampPoint: [28.7500, -25.8070],
        authorizedPolygon: [
          [28.7400, -25.8000],
          [28.7550, -25.8000],
          [28.7550, -25.8150],
          [28.7400, -25.8150],
          [28.7400, -25.8000]
        ],
        maxDwellMinutes: 30,
        allowedPurposes: ['WEIGHBRIDGE', 'GRAIN_INSPECTION']
      })
    });
    const newExcData = await newExcRes.json();
    if (!newExcData.success) throw new Error('Failed to create custom manager waypoint exception');
    console.log('✅ Manager Route Specification passed! Created:', newExcData.exception.name);
    testsPassed++;

    // Test 5: Telemetry Ingestion — Normal N4 Corridor Ping
    console.log('\n[Test 5] Telemetry Ingestion: Normal N4 Corridor Ping');
    const ping1Res = await fetch(`${baseUrl}/api/v1/telemetry/ping`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        truckId: 'FW-01',
        lat: -25.77266,
        lng: 28.43128,
        heading: 95,
        speed: 72,
        fuelLevelLiters: 480,
        batteryPercent: 95,
        isCharging: true,
        dwellMinutesAtStop: 0
      })
    });
    const ping1Data = await ping1Res.json();
    if (ping1Data.corridorStatus !== 'CORRIDOR_COMPLIANT') throw new Error(`Expected CORRIDOR_COMPLIANT, got ${ping1Data.corridorStatus}`);
    console.log('✅ Normal N4 Ping passed! Status:', ping1Data.corridorStatus, '| Zone:', ping1Data.zone);
    testsPassed++;

    // Test 6: Telemetry Ingestion — Rayton R515 Off-ramp & Truck Stop (Authorized Waypoint)
    console.log('\n[Test 6] Telemetry Ingestion: Rayton R515 Off-ramp (Authorized Waypoint)');
    // Rayton truck stop coordinates inside authorizedPolygon: [28.5300, -25.7600]
    const pingRaytonRes = await fetch(`${baseUrl}/api/v1/telemetry/ping`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        truckId: 'FW-01',
        lat: -25.7600,
        lng: 28.5300,
        heading: 0,
        speed: 0,
        fuelLevelLiters: 475,
        batteryPercent: 94,
        isCharging: true,
        dwellMinutesAtStop: 20 // 20 mins < 45m max dwell -> Should be AUTHORIZED_WAYPOINT!
      })
    });
    const pingRaytonData = await pingRaytonRes.json();
    if (pingRaytonData.corridorStatus !== 'AUTHORIZED_WAYPOINT') {
      throw new Error(`Expected AUTHORIZED_WAYPOINT, got ${pingRaytonData.corridorStatus}`);
    }
    console.log('✅ Rayton Authorized Off-ramp test passed! Status:', pingRaytonData.corridorStatus, '| Zone:', pingRaytonData.zone);
    console.log('   No false violation triggered because off-ramp was pre-authorized by manager!');
    testsPassed++;

    // Test 7: Telemetry Ingestion — Unauthorized Balmoral Dirt Detour (Toll Evasion)
    console.log('\n[Test 7] Telemetry Ingestion: Unauthorized R104 Dirt Bypass');
    const pingDetourRes = await fetch(`${baseUrl}/api/v1/telemetry/ping`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        truckId: 'FW-01',
        lat: -25.8350,
        lng: 28.8950,
        heading: 120,
        speed: 45,
        fuelLevelLiters: 460,
        batteryPercent: 92,
        isCharging: true,
        dwellMinutesAtStop: 0
      })
    });
    const pingDetourData = await pingDetourRes.json();
    if (pingDetourData.corridorStatus !== 'UNAUTHORIZED_DETOUR' || pingDetourData.alertsTriggered === 0) {
      throw new Error(`Expected UNAUTHORIZED_DETOUR with alert, got ${pingDetourData.corridorStatus}`);
    }
    const detourAlert = pingDetourData.alerts[0];
    console.log('✅ Unauthorized Detour test passed! Alert:', detourAlert.title);
    console.log('   Estimated Financial Risk:', `R ${detourAlert.financialImpactZAR.toLocaleString()}`);
    testsPassed++;

    // Test 8: Telemetry Ingestion — Fuel Siphon Detection
    console.log('\n[Test 8] Telemetry Ingestion: Fuel Siphon Detection');
    // Drop fuel from 460L to 380L (-80 Liters in stationary state)
    const pingSiphonRes = await fetch(`${baseUrl}/api/v1/telemetry/ping`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        truckId: 'FW-01',
        lat: -25.8350,
        lng: 28.8950,
        heading: 120,
        speed: 0,
        fuelLevelLiters: 380, // -80L drop
        batteryPercent: 90,
        isCharging: false,
        dwellMinutesAtStop: 10
      })
    });
    const pingSiphonData = await pingSiphonRes.json();
    const siphonAlert = pingSiphonData.alerts.find(a => a.type === 'FUEL_THEFT_CRITICAL');
    if (!siphonAlert) throw new Error('Siphon alert was not triggered for 80L sudden drop');
    console.log('✅ Siphon Detection passed! Alert:', siphonAlert.title);
    console.log('   Estimated Fuel Loss in ZAR:', `R ${siphonAlert.financialImpactZAR.toLocaleString()}`);
    testsPassed++;

    // Test 9: Outbound Driver WhatsApp Notice Log
    console.log('\n[Test 9] Multilingual WhatsApp Driver Notification Queue');
    const dispatchRes = await fetch(`${baseUrl}/api/v1/fleet/dispatches`);
    const dispatchData = await dispatchRes.json();
    if (dispatchData.count === 0) throw new Error('No WhatsApp dispatches recorded');
    const latestMsg = dispatchData.dispatches[0];
    console.log('✅ Outbound Notification passed! Total queued:', dispatchData.count);
    console.log('   Recipient:', latestMsg.driverName, `(${latestMsg.to})`);
    console.log('   Language:', latestMsg.language, '| Message preview:', latestMsg.message.substring(0, 75) + '...');
    testsPassed++;

    // Test 10: SARS Diesel Rebate Schedule (Schedule 6)
    console.log('\n[Test 10] SARS Diesel Rebate Schedule Export');
    const sarsRes = await fetch(`${baseUrl}/api/v1/fleet/reports/sars-diesel-logbook`);
    const sarsData = await sarsRes.json();
    if (!sarsData.success || !sarsData.totalProjectedRebateZAR) throw new Error('SARS report generation failed');
    console.log('✅ SARS Diesel Rebate Schedule passed!');
    console.log('   Haulier:', sarsData.haulier, '| VAT Number:', sarsData.vatNumber);
    console.log('   Total Projected Rebate:', `R ${sarsData.totalProjectedRebateZAR.toLocaleString()} ZAR`);
    testsPassed++;

    // Test 11: N4 High-Fidelity Journey Mule Dataset
    console.log('\n[Test 11] N4 High-Fidelity Journey Mule Dataset (Real-Time Cost Simulator)');
    const muleRes = await fetch(`${baseUrl}/api/v1/fleet/journey-mule`);
    const muleData = await muleRes.json();
    if (!muleData.success || muleData.totalSteps < 200) throw new Error('Journey mule endpoint failed');
    console.log('✅ N4 Journey Mule Endpoint passed!');
    console.log('   Route:', muleData.route);
    console.log('   Total Distance:', `${muleData.totalDistanceKm} km | Total Steps: ${muleData.totalSteps}`);
    console.log('   Starting Point:', muleData.waypoints[0].zone);
    console.log('   Arrival Point:', muleData.waypoints[muleData.waypoints.length - 1].zone);
    console.log('   Total Simulated Trip Expenditure:', `R ${muleData.waypoints[muleData.waypoints.length - 1].totalTripCostZAR.toLocaleString()} ZAR`);
    testsPassed++;

    console.log(`\n🎉 ALL ${testsPassed} INTEGRATION TESTS PASSED 100%!`);
    if (server.listening) {
      server.close(() => process.exit(0));
    } else {
      process.exit(0);
    }
  } catch (error) {
    console.error('\n❌ TEST FAILED:', error.message);
    if (server.listening) {
      server.close(() => process.exit(1));
    } else {
      process.exit(1);
    }
  }
}

runTests();
