package com.svaronam.jobradar

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Cada X minutos pregunta a la Pi (por Tailscale) si hay ofertas nuevas desde la última que vio, ya con su CV
 * preparado, y lanza una notificación por cada una. Si la Pi no responde no se pierde nada: el servidor
 * guarda el histórico y en la siguiente vuelta llegan.
 */
class Comprobador(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {

    override fun doWork(): Result {
        val p = Prefs(applicationContext)
        if (!p.configurado()) return Result.success()
        val ahora = SimpleDateFormat("dd/MM HH:mm", Locale("es")).format(Date())
        return try {
            val json = get("${p.servidor}/api/nuevas?desde=${p.ultimoId}&desde_alerta=${p.ultimaAlertaId}", p.token)

            val als = json.optJSONArray("alertas")
            if (p.ultimaAlertaId >= 0 && als != null) {
                for (i in 0 until minOf(als.length(), 3)) Avisos.alerta(applicationContext, als.getJSONObject(i))
            }
            p.ultimaAlertaId = maxOf(p.ultimaAlertaId, json.optLong("max_alerta", 0))

            val items = json.optJSONArray("items")
            val maxId = json.optLong("max_id", 0)
            val n = items?.length() ?: 0
            if (p.ultimoId >= 0 && n > 0) {
                val lista = (0 until n).map { items!!.getJSONObject(it) }
                val prioritarias = lista.count { it.optString("nivel") == "prioritaria" }
                val avisar = if (n <= 5) lista else lista.sortedByDescending { it.optInt("score") }.take(4)
                avisar.forEach { Avisos.oferta(applicationContext, it, logo(p, it)) }
                if (n > 1) Avisos.resumen(applicationContext, n, prioritarias)
            }
            // si vinieron 50 (el máximo por consulta) quedan más: avanzamos solo hasta la última recibida
            val ultimaRecibida = if (n > 0) items!!.getJSONObject(n - 1).optLong("id") else maxId
            p.ultimoId = if (n >= 50) ultimaRecibida else maxOf(maxId, ultimaRecibida)
            p.ultimaConsulta = "OK $ahora · $n ofertas nuevas"
            Result.success()
        } catch (e: Exception) {
            p.ultimaConsulta = "Sin conexión $ahora · ${e.message ?: e.javaClass.simpleName}"
            Result.success()
        }
    }

    /** Logo de la empresa desde la Pi; si no hay o falla, la notificación sale sin él. */
    private fun logo(p: Prefs, o: JSONObject): Bitmap? {
        if (o.optString("logo").let { it.isBlank() || it == "null" }) return null
        return try {
            val c = URL("${p.servidor}/api/ofertas/${o.getLong("id")}/logo").openConnection() as HttpURLConnection
            c.connectTimeout = 8000
            c.readTimeout = 10000
            if (p.token.isNotBlank()) c.setRequestProperty("X-Token", p.token)
            try {
                if (c.responseCode != 200) null else c.inputStream.use { BitmapFactory.decodeStream(it) }
            } finally {
                c.disconnect()
            }
        } catch (e: Exception) {
            null
        }
    }

    companion object {
        private const val NOMBRE = "jobradar-comprobar"

        fun get(url: String, token: String): JSONObject {
            val c = URL(url).openConnection() as HttpURLConnection
            c.connectTimeout = 15000
            c.readTimeout = 20000
            if (token.isNotBlank()) c.setRequestProperty("X-Token", token)
            try {
                if (c.responseCode == 401) throw IllegalStateException("Token incorrecto")
                return JSONObject(c.inputStream.bufferedReader().use { it.readText() })
            } finally {
                c.disconnect()
            }
        }

        fun programar(ctx: Context, reemplazar: Boolean = false) {
            val min = Prefs(ctx).minutos.coerceAtLeast(15).toLong()
            val req = PeriodicWorkRequestBuilder<Comprobador>(min, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(
                NOMBRE,
                if (reemplazar) ExistingPeriodicWorkPolicy.UPDATE else ExistingPeriodicWorkPolicy.KEEP,
                req)
        }

        fun ahora(ctx: Context) {
            WorkManager.getInstance(ctx).enqueue(OneTimeWorkRequestBuilder<Comprobador>().build())
        }
    }
}
