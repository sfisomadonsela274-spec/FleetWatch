package com.fleetsentinel.driver

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.Editable
import android.text.TextWatcher
import android.util.Log
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.BufferedReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

class PairingActivity : AppCompatActivity() {

    private lateinit var layoutPhoneStage: View
    private lateinit var etPhoneNumber: EditText
    private lateinit var btnRequestOtp: Button

    private lateinit var layoutOtpStage: View
    private lateinit var tvOtpPhoneTarget: TextView
    private lateinit var etOtpCode: EditText
    private lateinit var btnVerifyOtp: Button
    private lateinit var tvResendOtp: TextView
    private lateinit var tvChangePhone: TextView

    private lateinit var tvPairingError: TextView
    private lateinit var progressBar: ProgressBar
    private lateinit var tvToggleServerConfig: TextView
    private lateinit var etServerUrl: EditText

    private var currentPhoneNumber: String = ""
    private val activityScope = CoroutineScope(Dispatchers.Main + Job())

    companion object {
        private const val TAG = "PairingActivity"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // If already paired, proceed directly to MainActivity
        if (AppPreferences.isPaired(this)) {
            navigateToMain()
            return
        }

        setContentView(R.layout.activity_pairing)
        setupViews()
    }

    private fun setupViews() {
        layoutPhoneStage = findViewById(R.id.layoutPhoneStage)
        etPhoneNumber = findViewById(R.id.etPhoneNumber)
        btnRequestOtp = findViewById(R.id.btnRequestOtp)

        layoutOtpStage = findViewById(R.id.layoutOtpStage)
        tvOtpPhoneTarget = findViewById(R.id.tvOtpPhoneTarget)
        etOtpCode = findViewById(R.id.etOtpCode)
        btnVerifyOtp = findViewById(R.id.btnVerifyOtp)
        tvResendOtp = findViewById(R.id.tvResendOtp)
        tvChangePhone = findViewById(R.id.tvChangePhone)

        tvPairingError = findViewById(R.id.tvPairingError)
        progressBar = findViewById(R.id.pairingProgressBar)
        tvToggleServerConfig = findViewById(R.id.tvToggleServerConfig)
        etServerUrl = findViewById(R.id.etServerUrl)

        etServerUrl.setText(AppPreferences.getApiBaseUrl(this))

        tvToggleServerConfig.setOnClickListener {
            etServerUrl.visibility = if (etServerUrl.visibility == View.VISIBLE) View.GONE else View.VISIBLE
        }

        // Auto-format OTP code input (###-###)
        etOtpCode.addTextChangedListener(object : TextWatcher {
            private var isFormatting = false
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                if (isFormatting || s == null) return
                val digits = s.toString().replace("-", "").trim()
                if (digits.length > 3) {
                    isFormatting = true
                    val formatted = "${digits.substring(0, 3)}-${digits.substring(3, Math.min(6, digits.length))}"
                    etOtpCode.setText(formatted)
                    etOtpCode.setSelection(formatted.length)
                    isFormatting = false
                }
            }
        })

        btnRequestOtp.setOnClickListener {
            attemptRequestOtp()
        }

        tvResendOtp.setOnClickListener {
            attemptRequestOtp()
        }

        tvChangePhone.setOnClickListener {
            layoutOtpStage.visibility = View.GONE
            layoutPhoneStage.visibility = View.VISIBLE
            currentPhoneNumber = ""
            etOtpCode.setText("")
            hideError()
        }

        val btnDirectCodeEntry = findViewById<Button>(R.id.btnDirectCodeEntry)
        btnDirectCodeEntry?.setOnClickListener {
            layoutPhoneStage.visibility = View.GONE
            layoutOtpStage.visibility = View.VISIBLE
            tvOtpPhoneTarget.text = "Enter 6-digit in-cab code from dispatch pass"
            currentPhoneNumber = ""
            etOtpCode.setText("")
            etOtpCode.requestFocus()
            hideError()
        }

        btnVerifyOtp.setOnClickListener {
            attemptVerifyOtp()
        }
    }

    private fun attemptRequestOtp() {
        val input = etPhoneNumber.text.toString().trim()
        val isEmail = input.contains("@") && input.contains(".")
        val digitsOnly = input.replace("[^0-9]".toRegex(), "")

        if (!isEmail && digitsOnly.length < 9) {
            showError("Please enter a valid email address or cell number")
            return
        }

        val serverUrl = etServerUrl.text.toString().trim().removeSuffix("/")
        AppPreferences.setApiBaseUrl(this, serverUrl)

        hideError()
        setLoading(true)

        activityScope.launch {
            val result = withContext(Dispatchers.IO) {
                executeRequestOtpNetwork(serverUrl, input)
            }

            setLoading(false)

            if (result.isSuccess) {
                currentPhoneNumber = input
                layoutPhoneStage.visibility = View.GONE
                layoutOtpStage.visibility = View.VISIBLE
                val targetDesc = if (isEmail) "Email: $input" else "Cell: $input"
                tvOtpPhoneTarget.text = "Login code dispatched to $targetDesc"
                etOtpCode.requestFocus()
                Toast.makeText(
                    this@PairingActivity,
                    "Code sent! Enter the 6-digit code below.",
                    Toast.LENGTH_LONG
                ).show()
            } else {
                val errorMsg = result.exceptionOrNull()?.message ?: "Failed to request code. Please verify email or phone."
                showError(errorMsg)
            }
        }
    }

    private fun attemptVerifyOtp() {
        val rawInput = etOtpCode.text.toString().trim()
        val digitsOnly = rawInput.replace("-", "").trim()

        if (digitsOnly.length != 6) {
            showError("Please enter the 6-digit in-cab code (e.g. 565-492)")
            return
        }

        val formattedOtp = "${digitsOnly.substring(0, 3)}-${digitsOnly.substring(3, 6)}"
        val serverUrl = etServerUrl.text.toString().trim().removeSuffix("/")

        hideError()
        setLoading(true)

        activityScope.launch {
            val result = withContext(Dispatchers.IO) {
                executeVerifyOtpNetwork(serverUrl, currentPhoneNumber, formattedOtp)
            }

            setLoading(false)

            if (result.isSuccess) {
                val data = result.getOrNull()!!
                AppPreferences.savePairing(
                    context = this@PairingActivity,
                    driverId = data.driverId,
                    truckReg = data.truckReg,
                    driverName = data.driverName,
                    token = data.token,
                    baseUrl = serverUrl
                )
                Toast.makeText(
                    this@PairingActivity,
                    "Welcome ${data.driverName}! Connected to ${data.truckReg}",
                    Toast.LENGTH_LONG
                ).show()

                // Start LocationService for active continuous background tracking
                val serviceIntent = Intent(this@PairingActivity, LocationService::class.java)
                try {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        startForegroundService(serviceIntent)
                    } else {
                        startService(serviceIntent)
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to start LocationService after OTP verification", e)
                }

                navigateToMain()
            } else {
                val errorMsg = result.exceptionOrNull()?.message ?: "Verification failed. Check in-cab code."
                showError(errorMsg)
            }
        }
    }

    private fun executeRequestOtpNetwork(baseUrl: String, phone: String): Result<String> {
        return try {
            val endpoint = "$baseUrl/api/v1/driver/request-otp"
            val url = URL(endpoint)
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 8000
                readTimeout = 8000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }

            val isEmail = phone.contains("@")
            val requestBody = JSONObject().apply {
                put("identifier", phone)
                if (isEmail) {
                    put("email", phone)
                } else {
                    put("phone_number", phone)
                }
            }

            OutputStreamWriter(conn.outputStream).use { it.write(requestBody.toString()) }

            val code = conn.responseCode
            if (code in 200..299) {
                val responseText = conn.inputStream.bufferedReader().use(BufferedReader::readText)
                val json = JSONObject(responseText)
                Result.success(json.optString("message", "OTP sent"))
            } else {
                val errStream = conn.errorStream
                val errMsg = if (errStream != null) {
                    val errJson = JSONObject(errStream.bufferedReader().use(BufferedReader::readText))
                    errJson.optString("detail", "Request failed (HTTP $code)")
                } else {
                    "Request rejected by server (HTTP $code)"
                }
                Result.failure(Exception(errMsg))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Request OTP network error", e)
            Result.failure(Exception("Cannot reach server: ${e.localizedMessage}"))
        }
    }

    private data class VerifyResponseData(
        val driverId: String,
        val truckReg: String,
        val driverName: String,
        val token: String
    )

    private fun executeVerifyOtpNetwork(baseUrl: String, phone: String, otp: String): Result<VerifyResponseData> {
        return try {
            val endpoint = "$baseUrl/api/v1/driver/verify-otp"
            val url = URL(endpoint)
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 8000
                readTimeout = 8000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }

            val deviceUuid = try {
                Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID) ?: "android-device"
            } catch (e: Exception) {
                "android-device"
            }

            val requestBody = JSONObject().apply {
                put("otp_code", otp)
                if (phone.isNotEmpty()) {
                    put("identifier", phone)
                    if (phone.contains("@")) {
                        put("email", phone)
                    } else {
                        put("phone_number", phone)
                    }
                }
                put("device_uuid", deviceUuid)
                put("device_model", Build.MODEL ?: "Android Handset")
            }

            OutputStreamWriter(conn.outputStream).use { it.write(requestBody.toString()) }

            val code = conn.responseCode
            if (code in 200..299) {
                val responseText = conn.inputStream.bufferedReader().use(BufferedReader::readText)
                val json = JSONObject(responseText)
                val driverId = json.getString("driver_id")
                val truckReg = json.getString("truck_reg")
                val driverName = json.optString("driver_name", "Assigned Driver")
                val token = json.getString("bearer_token")
                Result.success(VerifyResponseData(driverId, truckReg, driverName, token))
            } else {
                val errStream = conn.errorStream
                val errMsg = if (errStream != null) {
                    val errJson = JSONObject(errStream.bufferedReader().use(BufferedReader::readText))
                    errJson.optString("detail", "Verification rejected (HTTP $code)")
                } else {
                    "Verification rejected by server (HTTP $code)"
                }
                Result.failure(Exception(errMsg))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Verify OTP network error", e)
            Result.failure(Exception("Cannot reach server: ${e.localizedMessage}"))
        }
    }

    private fun setLoading(loading: Boolean) {
        progressBar.visibility = if (loading) View.VISIBLE else View.GONE
        btnRequestOtp.isEnabled = !loading
        btnVerifyOtp.isEnabled = !loading
        etPhoneNumber.isEnabled = !loading
        etOtpCode.isEnabled = !loading
    }

    private fun showError(msg: String) {
        tvPairingError.text = msg
        tvPairingError.visibility = View.VISIBLE
    }

    private fun hideError() {
        tvPairingError.visibility = View.GONE
    }

    private fun navigateToMain() {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        startActivity(intent)
        finish()
    }

    override fun onDestroy() {
        super.onDestroy()
        activityScope.cancel()
    }
}
