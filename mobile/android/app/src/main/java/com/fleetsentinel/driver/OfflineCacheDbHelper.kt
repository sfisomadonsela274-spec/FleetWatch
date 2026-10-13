package com.fleetsentinel.driver

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONArray
import org.json.JSONObject

/**
 * Manages the local handset SQLite buffer (pings_cache).
 * Stores GPS pings during Highveld cellular dead zones (e.g. Bronkhorstspruit to Balmoral),
 * and drains the queue in chronological order in batches of 20 upon reconnection.
 */
class OfflineCacheDbHelper(context: Context) : SQLiteOpenHelper(context, DATABASE_NAME, null, DATABASE_VERSION) {

    companion object {
        const val DATABASE_NAME = "fleetsentinel_offline.db"
        const val DATABASE_VERSION = 1
        const val TABLE_PINGS = "pings_cache"

        const val COL_ID = "id"
        const val COL_PAYLOAD = "payload_json"
        const val COL_TIMESTAMP = "timestamp_millis"
        const val COL_RETRY_COUNT = "retry_count"
    }

    override fun onCreate(db: SQLiteDatabase) {
        val createTable = """
            CREATE TABLE $TABLE_PINGS (
                $COL_ID INTEGER PRIMARY KEY AUTOINCREMENT,
                $COL_PAYLOAD TEXT NOT NULL,
                $COL_TIMESTAMP INTEGER NOT NULL,
                $COL_RETRY_COUNT INTEGER DEFAULT 0
            );
        """.trimIndent()
        db.execSQL(createTable)
        db.execSQL("CREATE INDEX idx_pings_time ON $TABLE_PINGS($COL_TIMESTAMP);")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        db.execSQL("DROP TABLE IF EXISTS $TABLE_PINGS")
        onCreate(db)
    }

    /**
     * Enqueues an unacknowledged telemetry ping during network outage.
     */
    fun enqueuePing(payloadJson: String, timestampMillis: Long) {
        val db = writableDatabase
        val values = ContentValues().apply {
            put(COL_PAYLOAD, payloadJson)
            put(COL_TIMESTAMP, timestampMillis)
            put(COL_RETRY_COUNT, 0)
        }
        db.insert(TABLE_PINGS, null, values)
    }

    /**
     * Retrieves up to 20 oldest pings chronologically to drain upon reconnection.
     */
    fun peekBatch(batchSize: Int = 20): Pair<List<Long>, JSONArray> {
        val db = readableDatabase
        val ids = mutableListOf<Long>()
        val pingsArray = JSONArray()

        val cursor = db.query(
            TABLE_PINGS,
            arrayOf(COL_ID, COL_PAYLOAD),
            null, null, null, null,
            "$COL_TIMESTAMP ASC",
            batchSize.toString()
        )

        cursor.use {
            while (it.moveToNext()) {
                val id = it.getLong(it.getColumnIndexOrThrow(COL_ID))
                val jsonStr = it.getString(it.getColumnIndexOrThrow(COL_PAYLOAD))
                ids.add(id)
                pingsArray.put(JSONObject(jsonStr))
            }
        }

        return Pair(ids, pingsArray)
    }

    /**
     * Deletes successfully synchronized pings by ID.
     */
    fun deleteBatch(ids: List<Long>) {
        if (ids.isEmpty()) return
        val db = writableDatabase
        val idString = ids.joinToString(",")
        db.execSQL("DELETE FROM $TABLE_PINGS WHERE $COL_ID IN ($idString);")
    }

    /**
     * Returns total queued pings waiting for cellular uplink.
     */
    fun getQueueDepth(): Int {
        val db = readableDatabase
        val cursor = db.rawQuery("SELECT COUNT(*) FROM $TABLE_PINGS", null)
        var count = 0
        cursor.use {
            if (it.moveToFirst()) {
                count = it.getInt(0)
            }
        }
        return count
    }
}
