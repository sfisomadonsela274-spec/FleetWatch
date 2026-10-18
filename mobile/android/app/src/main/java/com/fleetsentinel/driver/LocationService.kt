package com.fleetsentinel.driver

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.*
import android.util.Log
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.*

class LocationService : Service(), LocationListener {

    private lateinit var locationManager: LocationManager
    private lateinit var dbHelper: OfflineCacheDbHelper
    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private var currentSpeedKmh: Float = 0.0f
    private var isTracking = false

    companion object {
        const val TAG = "LocationService"
        const val NOTIFICATION_CHANNEL_ID = "fleetsentinel_tracking_channel"
        const val NOTIFICATION_ID = 1001

        const val MOVING_INTERVAL_MS = 30000L      // 30 seconds while moving (>5 km/h)
        const val STATIONARY_INTERVAL_MS = 120000L // 120 seconds when stationary
    }

    override fun onCreate() {
        super.onCreate()
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        dbHelper = OfflineCacheDbHelper(this)
        createNotificationChannel()
        Log.i(TAG, "FleetSentinel LocationService created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!AppPreferences.isPaired(this)) {
            Log.w(TAG, "Handset is not paired to any vehicle. Halting service.")
            stopSelf()
            return START_NOT_STICKY
        }

        try {
            val truckReg = AppPreferences.getTruckReg(this)
            val notification = buildForegroundNotification("Active corridor monitoring for $truckReg")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
            Log.i(TAG, "Foreground service active with type LOCATION for $truckReg")

            if (!isTracking) {
                startLocationUpdates(MOVING_INTERVAL_MS)
                startQueueDrainLoop()
                isTracking = true
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException: Location permissions missing for foreground service", e)
            stopSelf()
            return START_NOT_STICKY
        } catch (e: Exception) {
            Log.e(TAG, "Exception starting foreground service", e)
            stopSelf()
            return START_NOT_STICKY
        }

        return START_STICKY
    }

    private var currentPollingIntervalMs: Long = MOVING_INTERVAL_MS
    private var lastPingTransmittedMs: Long = 0L

    private fun startLocationUpdates(intervalMs: Long) {
        try {
            locationManager.removeUpdates(this)
            currentPollingIntervalMs = intervalMs
            val minDistanceM = if (intervalMs == MOVING_INTERVAL_MS) 5.0f else 25.0f

            var registered = false
            if (locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER,
                    intervalMs,
                    minDistanceM,
                    this
                )
                registered = true
                Log.i(TAG, "Requested GPS updates at ${intervalMs}ms interval, minDistance: ${minDistanceM}m")
            }

            if (locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                locationManager.requestLocationUpdates(
                    LocationManager.NETWORK_PROVIDER,
                    intervalMs,
                    minDistanceM,
                    this
                )
                registered = true
                Log.i(TAG, "Requested Network location updates at ${intervalMs}ms interval")
            }

            if (!registered) {
                locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER,
                    intervalMs,
                    minDistanceM,
                    this
                )
            }

            sendInitialLocationFix()
        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException in startLocationUpdates", e)
        }
    }

    private fun sendInitialLocationFix() {
        try {
            val gpsLoc = if (locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)
            } else null

            val netLoc = if (locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                locationManager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
            } else null

            val bestLoc = when {
                gpsLoc != null && netLoc != null -> if (gpsLoc.time >= netLoc.time) gpsLoc else netLoc
                gpsLoc != null -> gpsLoc
                netLoc != null -> netLoc
                else -> null
            }

            if (bestLoc != null) {
                Log.i(TAG, "Acquired initial location fix: lat=${bestLoc.latitude}, lng=${bestLoc.longitude}")
                onLocationChanged(bestLoc)
            } else {
                Log.w(TAG, "No cached lastKnownLocation available yet, awaiting first GPS/Network fix")
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException querying lastKnownLocation", e)
        }
    }

    override fun onLocationChanged(location: Location) {
        val now = System.currentTimeMillis()
        currentSpeedKmh = location.speed * 3.6f // convert m/s to km/h

        // Adaptive polling: ONLY re-register updates if movement state switched
        val targetInterval = if (currentSpeedKmh > 5.0f) MOVING_INTERVAL_MS else STATIONARY_INTERVAL_MS
        if (targetInterval != currentPollingIntervalMs) {
            startLocationUpdates(targetInterval)
        }

        // Software rate limiter: throttle transmission to minimum 10s moving, 30s stationary
        val minInterval = if (currentSpeedKmh > 5.0f) 10000L else 30000L
        if (now - lastPingTransmittedMs < minInterval && lastPingTransmittedMs != 0L) {
            return
        }
        lastPingTransmittedMs = now

        val driverId = AppPreferences.getDriverId(this)
        val truckReg = AppPreferences.getTruckReg(this)
        val (batteryPct, isCharging) = getBatteryStatus()
        val nowIso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }.format(Date())

        val payload = JSONObject().apply {
            put("driver_id", driverId)
            put("truck_reg", truckReg)
            put("lat", location.latitude)
            put("lng", location.longitude)
            put("speed_kmh", currentSpeedKmh.toDouble())
            put("battery_pct", batteryPct)
            put("is_charging", isCharging)
            put("timestamp", nowIso)
        }

        Log.i(TAG, "GPS Fix: driver=$driverId, truck=$truckReg, lat=${location.latitude}, lng=${location.longitude}, speed=${currentSpeedKmh}km/h, batt=${batteryPct}%")

        serviceScope.launch {
            transmitPing(payload.toString(), now)
        }

        updateNotification("$truckReg: ${currentSpeedKmh.toInt()} km/h • Batt: $batteryPct%")
    }

    private suspend fun transmitPing(jsonString: String, timestampMillis: Long) {
        val baseUrl = AppPreferences.getApiBaseUrl(this)
        val success = postJson("$baseUrl/api/v1/telemetry/ping", jsonString)
        if (success) {
            Log.i(TAG, "Telemetry ping transmitted successfully to $baseUrl")
        } else {
            // Buffer locally in SQLite during dead zones
            dbHelper.enqueuePing(jsonString, timestampMillis)
            val queueSize = dbHelper.getQueueDepth()
            Log.w(TAG, "Network unreachable. Buffered ping in SQLite cache. Queue depth: $queueSize")
        }
    }

    /**
     * Drains cached pings upon network reconnect in batches of 20.
     */
    private fun startQueueDrainLoop() {
        serviceScope.launch {
            while (isActive) {
                delay(15000) // check queue every 15s
                val queueDepth = dbHelper.getQueueDepth()
                if (queueDepth > 0) {
                    val (ids, batchArray) = dbHelper.peekBatch(20)
                    val batchPayload = JSONObject().apply {
                        put("pings", batchArray)
                    }

                    val baseUrl = AppPreferences.getApiBaseUrl(this@LocationService)
                    Log.i(TAG, "Attempting batch sync for ${ids.size} pings...")
                    val success = postJson("$baseUrl/api/v1/telemetry/batch", batchPayload.toString())
                    if (success) {
                        dbHelper.deleteBatch(ids)
                        val remaining = dbHelper.getQueueDepth()
                        Log.i(TAG, "Successfully drained ${ids.size} pings! Remaining in cache: $remaining")
                    } else {
                        Log.w(TAG, "Batch drainage failed, will retry in 15s")
                    }
                }
            }
        }
    }

    private fun postJson(urlString: String, jsonBody: String): Boolean {
        return try {
            val token = AppPreferences.getBearerToken(this)
            val url = URL(urlString)
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 6000
                readTimeout = 6000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                setRequestProperty("Authorization", "Bearer $token")
            }

            OutputStreamWriter(conn.outputStream).use { it.write(jsonBody) }
            val code = conn.responseCode

            if (code == 403) {
                // Device was revoked / decommissioned by Dispatcher!
                Log.w(TAG, "Received HTTP 403 Revoked: Handset decommissioned by Dispatch. Halting telemetry.")
                conn.disconnect()
                handleUnitRevoked()
                return false
            }

            val isSuccess = code in 200..299
            if (!isSuccess) {
                val errBody = try { conn.errorStream?.bufferedReader()?.readText() ?: "" } catch (e: Exception) { "" }
                Log.w(TAG, "HTTP $code failure ($urlString): $errBody")
            }

            conn.disconnect()
            isSuccess
        } catch (e: Exception) {
            Log.w(TAG, "HTTP POST failed ($urlString): ${e.localizedMessage}")
            false
        }
    }

    private fun handleUnitRevoked() {
        serviceScope.launch(Dispatchers.Main) {
            AppPreferences.clearPairing(applicationContext)
            updateNotification("FleetSentinel: Unit Decommissioned. Telemetry revoked.")
            stopSelf()
        }
    }

    private fun getBatteryStatus(): Pair<Int, Boolean> {
        val intentFilter = IntentFilter(Intent.ACTION_BATTERY_CHANGED)
        val batteryStatus = registerReceiver(null, intentFilter)
        val level = batteryStatus?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = batteryStatus?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val pct = if (level != -1 && scale != -1) (level * 100 / scale) else 100

        val status = batteryStatus?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val isCharging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
                status == BatteryManager.BATTERY_STATUS_FULL
        return Pair(pct, isCharging)
    }

    private fun buildForegroundNotification(contentText: String): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, NOTIFICATION_CHANNEL_ID)
            .setContentTitle("FleetSentinel Active — N4 Corridor")
            .setContentText(contentText)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun updateNotification(contentText: String) {
        val notification = buildForegroundNotification(contentText)
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIFICATION_ID, notification)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                NOTIFICATION_CHANNEL_ID,
                "FleetSentinel Location Tracking",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Monitors vehicle adherence to N4 Highveld freight corridor"
            }
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        Log.i(TAG, "FleetSentinel LocationService destroyed")
        locationManager.removeUpdates(this)
        serviceScope.cancel()
    }

    override fun onBind(intent: Intent?): IBinder? = null
    override fun onProviderEnabled(provider: String) {}
    override fun onProviderDisabled(provider: String) {}
}
