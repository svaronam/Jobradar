package com.svaronam.jobradar

import android.content.Context

/** Ajustes guardados en el móvil: dirección del servidor en la Pi, token y última oferta notificada. */
class Prefs(ctx: Context) {
    private val sp = ctx.getSharedPreferences("jobradar", Context.MODE_PRIVATE)

    var servidor: String
        get() = sp.getString("servidor", "") ?: ""
        set(v) = sp.edit().putString("servidor", v.trim().trimEnd('/')).apply()

    var token: String
        get() = sp.getString("token", "") ?: ""
        set(v) = sp.edit().putString("token", v.trim()).apply()

    /** -1 = nunca ha consultado (la primera vez no notifica lo que ya había). */
    var ultimoId: Long
        get() = sp.getLong("ultimo_id", -1L)
        set(v) = sp.edit().putLong("ultimo_id", v).apply()

    var ultimaAlertaId: Long
        get() = sp.getLong("ultima_alerta_id", -1L)
        set(v) = sp.edit().putLong("ultima_alerta_id", v).apply()

    var minutos: Int
        get() = sp.getInt("minutos", 30)
        set(v) = sp.edit().putInt("minutos", v).apply()

    var ultimaConsulta: String
        get() = sp.getString("ultima_consulta", "") ?: ""
        set(v) = sp.edit().putString("ultima_consulta", v).apply()

    /** Servicio en primer plano que recibe las ofertas al momento (si no, solo el comprobador periódico). */
    var alMomento: Boolean
        get() = sp.getBoolean("al_momento", true)
        set(v) = sp.edit().putBoolean("al_momento", v).apply()

    fun configurado() = servidor.startsWith("http")

    /** URL del servidor con el token en la query (para la WebView y las descargas). */
    fun url(ruta: String): String {
        val base = servidor + ruta
        if (token.isBlank()) return base
        val sep = if (base.contains("?")) "&" else "?"
        return base + sep + "token=" + android.net.Uri.encode(token)
    }
}
