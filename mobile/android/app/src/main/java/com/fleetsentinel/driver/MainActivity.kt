package com.fleetsentinel.driver

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private lateinit var dbHelper: OfflineCacheDbHelper
    private lateinit var tvStatus: TextView
    private lateinit var tvQueueDepth: TextView
    private lateinit var tvDriverInfo: TextView
    private lateinit var tvTruckInfo: TextView
    private lateinit var btnToggleTracking: Button
    private lateinit var btnBatteryWhitelist: Button
    private lateinit var btnForceSync: Button
    private lateinit var btnUnpair: Button
    private var isServiceRunning = false

    companion object {
        const val PERMISSION_REQUEST_CODE = 2001
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Enforce pairing before accessing the main portal
        if (!AppPreferences.isPaired(this)) {
            startActivity(Intent(this, PairingActivity::class.java))
            finish()
            return
        }

        setContentView(R.layout.activity_main)

        dbHelper = OfflineCacheDbHelper(this)
        setupUI()
        checkPermissions()
    }

    private fun setupUI() {
        title = getString(R.string.title_activity_main)
        tvStatus = findViewById(R.id.tvStatus)
        tvQueueDepth = findViewById(R.id.tvQueueDepth)
        tvDriverInfo = findViewById(R.id.tvDriverInfo)
        tvTruckInfo = findViewById(R.id.tvTruckInfo)
        btnToggleTracking = findViewById(R.id.btnToggleTracking)
        btnBatteryWhitelist = findViewById(R.id.btnBatteryWhitelist)
        btnForceSync = findViewById(R.id.btnForceSync)
        btnUnpair = findViewById(R.id.btnUnpair)

        updateVehicleDisplay()

        btnToggleTracking.setOnClickListener {
            if (!isServiceRunning) {
                startTrackingService()
            } else {
                stopTrackingService()
            }
        }

        btnBatteryWhitelist.setOnClickListener {
            BatteryOptimizationHelper.requestIgnoreBatteryOptimizations(this)
        }

        btnForceSync.setOnClickListener {
            val depth = dbHelper.getQueueDepth()
            if (depth == 0) {
                Toast.makeText(this, "Local cache empty — fully synchronized with N4 cloud", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "Triggering manual uplink flush of $depth pings...", Toast.LENGTH_SHORT).show()
            }
            updateQueueDisplay()
        }

        btnUnpair.setOnClickListener {
            stopTrackingService()
            AppPreferences.clearPairing(this)
            Toast.makeText(this, "Handset unpaired from vehicle", Toast.LENGTH_SHORT).show()
            val intent = Intent(this, PairingActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            }
            startActivity(intent)
            finish()
        }

        updateQueueDisplay()

        // Auto-start tracking service on portal launch if permissions granted
        if (hasLocationPermissions() && !isServiceRunning) {
            startTrackingService()
        }
    }

    private fun updateVehicleDisplay() {
        val driverName = AppPreferences.getDriverName(this)
        val driverId = AppPreferences.getDriverId(this)
        val truckReg = AppPreferences.getTruckReg(this)
        tvDriverInfo.text = "Driver: $driverName ($driverId)"
        tvTruckInfo.text = "Vehicle: $truckReg (Highveld Corridor)"
    }

    private fun hasLocationPermissions(): Boolean {
        val fineGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val coarseGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        return fineGranted || coarseGranted
    }

    private fun startTrackingService() {
        if (!hasLocationPermissions()) {
            checkPermissions()
            Toast.makeText(this, "Location permission required to track N4 corridor. Please grant permission in the dialog.", Toast.LENGTH_LONG).show()
            return
        }

        val intent = Intent(this, LocationService::class.java)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
            isServiceRunning = true
            tvStatus.text = getString(R.string.status_service_active)
            tvStatus.setTextColor(ContextCompat.getColor(this, R.color.emerald_dark))
            btnToggleTracking.text = getString(R.string.btn_stop_tracking)
            btnToggleTracking.setBackgroundColor(ContextCompat.getColor(this, R.color.rose_alert))
            Toast.makeText(this, "FleetSentinel Tracking active on N4 Corridor", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "Failed to start service", e)
            Toast.makeText(this, "Could not start service: ${e.localizedMessage}", Toast.LENGTH_LONG).show()
        }
    }

    private fun stopTrackingService() {
        val intent = Intent(this, LocationService::class.java)
        stopService(intent)
        isServiceRunning = false
        tvStatus.text = getString(R.string.status_service_stopped)
        tvStatus.setTextColor(ContextCompat.getColor(this, R.color.text_muted))
        btnToggleTracking.text = getString(R.string.btn_start_tracking)
        btnToggleTracking.setBackgroundColor(ContextCompat.getColor(this, R.color.accent_emerald))
        Toast.makeText(this, "Tracking paused", Toast.LENGTH_SHORT).show()
    }

    private fun checkPermissions() {
        val permissions = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION
        )

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }

        val missing = permissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (missing.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, missing.toTypedArray(), PERMISSION_REQUEST_CODE)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST_CODE) {
            if (hasLocationPermissions()) {
                Toast.makeText(this, "Permissions granted! You can now start tracking.", Toast.LENGTH_SHORT).show()
                startTrackingService()
            } else {
                Toast.makeText(this, "Location permission is required for N4 corridor monitoring.", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun updateQueueDisplay() {
        val depth = dbHelper.getQueueDepth()
        tvQueueDepth.text = getString(R.string.queue_status_format, depth)
    }

    override fun onResume() {
        super.onResume()
        if (!AppPreferences.isPaired(this)) {
            startActivity(Intent(this, PairingActivity::class.java))
            finish()
            return
        }
        updateVehicleDisplay()
        updateQueueDisplay()
    }
}
