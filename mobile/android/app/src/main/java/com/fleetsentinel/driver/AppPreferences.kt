package com.fleetsentinel.driver

import android.content.Context
import android.content.SharedPreferences

/**
 * Manages persistent in-cab credentials and pairing state.
 * Prevents hardcoding and allows dynamic driver dispatch & offboarding.
 */
object AppPreferences {

    private const val PREFS_NAME = "fleetsentinel_driver_prefs"
    private const val KEY_IS_PAIRED = "key_is_paired"
    private const val KEY_DRIVER_ID = "key_driver_id"
    private const val KEY_TRUCK_REG = "key_truck_reg"
    private const val KEY_DRIVER_NAME = "key_driver_name"
    private const val KEY_BEARER_TOKEN = "key_bearer_token"
    private const val KEY_API_BASE_URL = "key_api_base_url"

    private const val DEFAULT_API_BASE_URL = "http://127.0.0.1:8001"
    private const val DEFAULT_TOKEN = "fleetsentinel_pilot_secret_token_2026"

    private fun getPrefs(context: Context): SharedPreferences {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    }

    fun isPaired(context: Context): Boolean {
        return getPrefs(context).getBoolean(KEY_IS_PAIRED, false)
    }

    fun getDriverId(context: Context): String {
        return getPrefs(context).getString(KEY_DRIVER_ID, "DRV-01") ?: "DRV-01"
    }

    fun getTruckReg(context: Context): String {
        return getPrefs(context).getString(KEY_TRUCK_REG, "WP 889 GP") ?: "WP 889 GP"
    }

    fun getDriverName(context: Context): String {
        return getPrefs(context).getString(KEY_DRIVER_NAME, "Sipho Dlamini") ?: "Sipho Dlamini"
    }

    fun getBearerToken(context: Context): String {
        return getPrefs(context).getString(KEY_BEARER_TOKEN, DEFAULT_TOKEN) ?: DEFAULT_TOKEN
    }

    fun getApiBaseUrl(context: Context): String {
        return getPrefs(context).getString(KEY_API_BASE_URL, DEFAULT_API_BASE_URL) ?: DEFAULT_API_BASE_URL
    }

    fun savePairing(
        context: Context,
        driverId: String,
        truckReg: String,
        driverName: String,
        token: String,
        baseUrl: String = DEFAULT_API_BASE_URL
    ) {
        getPrefs(context).edit().apply {
            putBoolean(KEY_IS_PAIRED, true)
            putString(KEY_DRIVER_ID, driverId)
            putString(KEY_TRUCK_REG, truckReg)
            putString(KEY_DRIVER_NAME, driverName)
            putString(KEY_BEARER_TOKEN, token)
            putString(KEY_API_BASE_URL, baseUrl)
            apply()
        }
    }

    fun setApiBaseUrl(context: Context, baseUrl: String) {
        getPrefs(context).edit().putString(KEY_API_BASE_URL, baseUrl).apply()
    }

    fun clearPairing(context: Context) {
        getPrefs(context).edit().apply {
            putBoolean(KEY_IS_PAIRED, false)
            remove(KEY_DRIVER_ID)
            remove(KEY_TRUCK_REG)
            remove(KEY_DRIVER_NAME)
            remove(KEY_BEARER_TOKEN)
            apply()
        }
    }
}
