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
        // con "Avisos al momento" conectado ya se encarga el servicio; esto queda de respaldo
        if (Servicio.conectado) return Result.success()
        consultar(applicationContext)
        return Result.success()
    }

    companion object {
        private const val NOMBRE = "jobradar-comprobar"
        private val cerrojo = Any()

        /**
         * Pregunta a la Pi por ofertas y alertas nuevas y las notifica. wait > 0 deja la petición abierta hasta
         * que haya algo (máx. 55 s): así trabaja el servicio de avisos al momento. Devuelve cuántas ofertas llegaron
         * o lanza la excepción si no llega a la Pi.
         */
        fun consultar(ctx: Context, wait: Int = 0, lanzar: Boolean = false): Int {
            val p = Prefs(ctx)
            if (!p.configurado()) return 0
            val ahora = SimpleDateFormat("dd/MM HH:mm", Locale("es")).format(Date())
            try {
                val url = "${p.servidor}/api/nuevas?desde=${p.ultimoId}&desde_alerta=${p.ultimaAlertaId}&wait=$wait"
                val json = get(url, p.token, if (wait > 0) (wait + 20) * 1000 else 20000)
                synchronized(cerrojo) {
                    val als = json.optJSONArray("alertas")
                    if (p.ultimaAlertaId >= 0 && als != null) {
                        for (i in 0 until minOf(als.length(), 3)) Avisos.alerta(ctx, als.getJSONObject(i))
                    }
                    p.ultimaAlertaId = maxOf(p.ultimaAlertaId, json.optLong("max_alerta", 0))

                    val items = json.optJSONArray("items")
                    val maxId = json.optLong("max_id", 0)
                    // solo las que no se hayan notificado ya (por si el servicio y el respaldo se cruzan)
                    val lista = if (items == null) emptyList() else
                        (0 until items.length()).map { items.getJSONObject(it) }.filter { it.optLong("id") > p.ultimoId }
                    val n = lista.size
                    if (p.ultimoId >= 0 && n > 0) {
                        val prioritarias = lista.count { it.optString("nivel") == "prioritaria" }
                        val avisar = if (n <= 5) lista else lista.sortedByDescending { it.optInt("score") }.take(4)
                        avisar.forEach { Avisos.oferta(ctx, it, logo(p, it)) }
                        if (n > 1) Avisos.resumen(ctx, n, prioritarias)
                    }
                    // si vinieron 50 (el máximo por consulta) quedan más: avanzamos solo hasta la última recibida
                    val ultimaRecibida = if (n > 0) lista.last().optLong("id") else maxId
                    p.ultimoId = if ((items?.length() ?: 0) >= 50) ultimaRecibida else maxOf(p.ultimoId, maxId, ultimaRecibida)
                    p.ultimaConsulta = "OK $ahora · $n ofertas nuevas"
                    return n
                }
            } catch (e: Exception) {
                p.ultimaConsulta = "Sin conexión $ahora · ${e.message ?: e.javaClass.simpleName}"
                if (lanzar) throw e
                return 0
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


        fun get(url: String, token: String, readTimeout: Int = 20000): JSONObject {
            val c = URL(url).openConnection() as HttpURLConnection
            c.connectTimeout = 15000
            c.readTimeout = readTimeout
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
