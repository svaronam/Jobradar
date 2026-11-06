package com.svaronam.jobradar

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.drawable.Icon
import android.net.Uri
import org.json.JSONObject

/** Notificaciones nativas, un canal por nivel (el sonido de cada uno se ajusta en Ajustes de Android). */
object Avisos {
    const val CANAL_PRIORITARIA = "prioritaria"
    const val CANAL_INTERESANTE = "interesante"
    const val CANAL_VIGILAR = "vigilar"
    const val CANAL_RESUMEN = "resumen"
    const val CANAL_ESTADO = "estado"
    const val CANAL_FIJA = "fija"
    const val CANAL_DIA = "resumen_dia"
    const val CANAL_CAND = "candidaturas"
    const val ID_FIJA = 4

    fun crearCanales(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CANAL_PRIORITARIA, "Prioritarias (≥75)",
            NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Ofertas que encajan muy bien contigo: suena y aparece arriba"
            enableLights(true); lightColor = Color.parseColor("#2563EB"); enableVibration(true)
        })
        nm.createNotificationChannel(NotificationChannel(CANAL_INTERESANTE, "Interesantes (58-74)",
            NotificationManager.IMPORTANCE_DEFAULT).apply { description = "Merecen un vistazo" })
        nm.createNotificationChannel(NotificationChannel(CANAL_VIGILAR, "A vigilar (40-57)",
            NotificationManager.IMPORTANCE_LOW).apply { description = "Sin sonido" })
        nm.createNotificationChannel(NotificationChannel(CANAL_ESTADO, "⚠ Estado del radar",
            NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "Si LinkedIn limita las peticiones o cambia su página"
        })
        nm.createNotificationChannel(NotificationChannel(CANAL_DIA, "📰 Resumen del día",
            NotificationManager.IMPORTANCE_DEFAULT).apply { description = "Las mejores ofertas del día que aún no has abierto" })
        nm.createNotificationChannel(NotificationChannel(CANAL_CAND, "📋 Candidaturas",
            NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "Recordatorios cuando una candidatura lleva días sin novedades"
        })
        nm.createNotificationChannel(NotificationChannel(CANAL_FIJA, "Avisos al momento (fija)",
            NotificationManager.IMPORTANCE_MIN).apply {
            description = "Notificación fija mientras la app escucha a la Pi. Puedes ocultarla aquí sin que se pare"
            setShowBadge(false)
        })
        nm.createNotificationChannel(NotificationChannel(CANAL_RESUMEN, "Resúmenes",
            NotificationManager.IMPORTANCE_LOW).apply { description = "Cuando llegan muchas a la vez" })
    }

    private fun abrirApp(ctx: Context, ancla: String, cvId: Long = 0): PendingIntent {
        val i = Intent(ctx, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("ancla", ancla)
            if (cvId > 0) putExtra("cv_id", cvId)
        }
        return PendingIntent.getActivity(ctx, (ancla + cvId).hashCode(), i,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun abrirEnlace(ctx: Context, url: String, codigo: Int): PendingIntent {
        val i = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply { flags = Intent.FLAG_ACTIVITY_NEW_TASK }
        return PendingIntent.getActivity(ctx, codigo, i, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private val MODO = mapOf("remoto" to "Remoto", "remoto?" to "Remoto (pide oficina)",
        "remoto_nc" to "Remoto sin confirmar", "hibrido" to "Híbrido", "presencial" to "Presencial")

    private fun txt(o: JSONObject, k: String) = o.optString(k).takeIf { it.isNotBlank() && it != "null" }

    /** "🔵 92 · Backend Developer Java" / "Empresa · Remoto · 42–50k €" con el desglose al desplegar. */
    fun oferta(ctx: Context, o: JSONObject, logo: Bitmap? = null) {
        val id = o.getLong("id")
        val nivel = o.optString("nivel")
        val canal = when (nivel) {
            "prioritaria" -> CANAL_PRIORITARIA
            "interesante" -> CANAL_INTERESANTE
            else -> CANAL_VIGILAR
        }
        val emoji = when (nivel) { "prioritaria" -> "🔴"; "interesante" -> "🟠"; else -> "🔵" }
        val color = when (nivel) { "prioritaria" -> "#C2410C"; "interesante" -> "#B7791F"; else -> "#2F6F9F" }
        val modo = MODO[o.optString("modalidad")]
        val km = if (o.has("km") && !o.isNull("km") && o.optString("modalidad") != "remoto") "~${o.optInt("km")} km" else null
        val sueldo = if (!o.isNull("sueldo_max") && o.optInt("sueldo_max") > 0) {
            val a = o.optInt("sueldo_min") / 1000; val b = o.optInt("sueldo_max") / 1000
            if (a == b) "${b}k €" else "$a–${b}k €"
        } else null
        val linea = listOfNotNull(txt(o, "empresa"), modo, km, sueldo).joinToString(" · ")

        val desglose = o.optJSONArray("desglose")
        val porQue = if (desglose != null) (0 until desglose.length()).mapNotNull { i ->
            val d = desglose.optJSONArray(i) ?: return@mapNotNull null
            val p = d.optInt(1)
            "${if (p > 0) "+" else ""}$p  ${d.optString(0)}"
        }.joinToString("\n") else ""
        val falta = o.optJSONObject("encaje")?.optJSONArray("falta")?.let { a ->
            (0 until a.length()).joinToString(", ") { a.getString(it) } }?.takeIf { it.isNotBlank() }
        val cvListo = o.optString("cv_estado") == "ok"
        val cuerpo = buildString {
            append(linea)
            txt(o, "lugar")?.let { append("\n📍 ").append(it) }
            if (cvListo) append("\n📄 CV adaptado listo (").append(o.optString("cv_idioma").uppercase()).append(")")
            if (falta != null) append("\n✗ Pide y no tienes: ").append(falta)
            if (porQue.isNotBlank()) append("\n\n").append(porQue)
        }

        val b = Notification.Builder(ctx, canal)
            .setSmallIcon(R.drawable.ic_stat)
            .setColor(Color.parseColor(color))
            .setLargeIcon(logo)  // logo de la empresa (null = sin icono grande)
            .setContentTitle("$emoji ${o.optInt("score")} · ${o.optString("titulo")}")
            .setContentText(linea)
            .setStyle(Notification.BigTextStyle().bigText(cuerpo))
            .setSubText(if (cvListo) "CV listo" else "LinkedIn")
            .setAutoCancel(true)
            .setGroup("jobradar")
            .setContentIntent(abrirApp(ctx, "oferta-$id"))
        txt(o, "url")?.let {
            b.addAction(Notification.Action.Builder(null as Icon?, "Abrir en LinkedIn", abrirEnlace(ctx, it, (id * 10 + 1).toInt())).build())
        }
        if (cvListo) {
            b.addAction(Notification.Action.Builder(null as Icon?, "Ver CV", abrirApp(ctx, "oferta-$id", id)).build())
        }
        ctx.getSystemService(NotificationManager::class.java).notify((id + 1000).toInt(), b.build())
    }

    fun fija(ctx: Context, texto: String): Notification =
        Notification.Builder(ctx, CANAL_FIJA)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("JobRadar")
            .setContentText(texto)
            .setOngoing(true)
            .setShowWhen(false)
            .setContentIntent(abrirApp(ctx, ""))
            .build()

    fun actualizarFija(ctx: Context, texto: String) {
        ctx.getSystemService(NotificationManager::class.java).notify(ID_FIJA, fija(ctx, texto))
    }

    fun resumen(ctx: Context, total: Int, prioritarias: Int) {
        val n = Notification.Builder(ctx, CANAL_RESUMEN)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("$total ofertas nuevas")
            .setContentText(if (prioritarias > 0) "$prioritarias prioritarias · toca para verlas" else "Toca para verlas")
            .setAutoCancel(true)
            .setGroup("jobradar")
            .setGroupSummary(true)
            .setContentIntent(abrirApp(ctx, ""))
            .build()
        ctx.getSystemService(NotificationManager::class.java).notify(1, n)
    }

    fun alerta(ctx: Context, a: JSONObject) {
        when (a.optString("tipo")) {
            "resumen" -> return resumenDia(ctx, a)
            "seguimiento" -> return recordatorio(ctx, a)
        }
        val n = Notification.Builder(ctx, CANAL_ESTADO)
            .setSmallIcon(R.drawable.ic_stat)
            .setColor(Color.parseColor("#B7791F"))
            .setContentTitle("⚠ JobRadar")
            .setContentText(a.optString("texto"))
            .setStyle(Notification.BigTextStyle().bigText(a.optString("texto")))
            .setAutoCancel(true)
            .setContentIntent(abrirApp(ctx, ""))
            .build()
        ctx.getSystemService(NotificationManager::class.java).notify(900000 + a.optInt("id"), n)
    }

    /** "📰 3 ofertas de hoy sin abrir" con una línea por oferta. */
    private fun resumenDia(ctx: Context, a: JSONObject) {
        val ofertas = a.optJSONArray("datos")
        val estilo = Notification.InboxStyle()
        val total = ofertas?.length() ?: 0
        for (i in 0 until total) {
            val o = ofertas!!.getJSONObject(i)
            estilo.addLine("${o.optInt("score")} · ${o.optString("titulo")} · ${o.optString("empresa")}")
        }
        val titulo = if (total == 1) "📰 La mejor oferta de hoy sin abrir" else "📰 Las $total mejores ofertas de hoy sin abrir"
        estilo.setBigContentTitle(titulo)
        val primera = if (total > 0) ofertas!!.getJSONObject(0) else null
        val n = Notification.Builder(ctx, CANAL_DIA)
            .setSmallIcon(R.drawable.ic_stat)
            .setColor(Color.parseColor("#2563EB"))
            .setContentTitle(titulo)
            .setContentText(primera?.let { "${it.optInt("score")} · ${it.optString("titulo")} · ${it.optString("empresa")}" } ?: "")
            .setStyle(estilo)
            .setAutoCancel(true)
            .setContentIntent(abrirApp(ctx, primera?.let { "oferta-${it.optLong("id")}" } ?: ""))
            .build()
        ctx.getSystemService(NotificationManager::class.java).notify(5, n)
    }

    /** "⏰ Hace 7 días que aplicaste a… escribe al recruiter": abre la pestaña Candidaturas. */
    private fun recordatorio(ctx: Context, a: JSONObject) {
        val n = Notification.Builder(ctx, CANAL_CAND)
            .setSmallIcon(R.drawable.ic_stat)
            .setColor(Color.parseColor("#B7791F"))
            .setContentTitle("⏰ Candidatura sin novedades")
            .setContentText(a.optString("texto"))
            .setStyle(Notification.BigTextStyle().bigText(a.optString("texto")))
            .setAutoCancel(true)
            .setContentIntent(abrirApp(ctx, "candidaturas"))
            .build()
        ctx.getSystemService(NotificationManager::class.java).notify(700000 + a.optInt("oferta_id"), n)
    }

    fun prueba(ctx: Context) {
        val n = Notification.Builder(ctx, CANAL_PRIORITARIA)
            .setSmallIcon(R.drawable.ic_stat)
            .setColor(Color.parseColor("#C2410C"))
            .setContentTitle("🔴 100 · Notificación de prueba")
            .setContentText("Empresa · Remoto · 45–50k €")
            .setAutoCancel(true)
            .setContentIntent(abrirApp(ctx, ""))
            .build()
        ctx.getSystemService(NotificationManager::class.java).notify(2, n)
    }
}
