package com.svaronam.jobradar

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * "Avisos al momento": servicio en primer plano que deja abierta una petición a la Pi (long-poll por Tailscale).
 * La Pi contesta en cuanto una oferta nueva tiene su CV listo, así que el aviso llega en segundos y no a los
 * 15-30 min del comprobador periódico, que sigue de respaldo por si el servicio se para.
 */
class Servicio : Service() {

    companion object {
        @Volatile var conectado = false
            private set

        fun arrancar(ctx: Context) {
            val p = Prefs(ctx)
            if (!p.configurado() || !p.alMomento) return
            ContextCompat.startForegroundService(ctx, Intent(ctx, Servicio::class.java))
        }

        fun parar(ctx: Context) {
            ctx.stopService(Intent(ctx, Servicio::class.java))
        }

        fun reiniciar(ctx: Context) {
            parar(ctx)
            arrancar(ctx)
        }
    }

    @Volatile private var activo = false
    private var hilo: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Avisos.crearCanales(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val tipo = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, Avisos.ID_FIJA, Avisos.fija(this, "Conectando con la Pi…"), tipo)
        if (!activo) {
            activo = true
            hilo = Thread({ bucle() }, "jobradar-avisos").also { it.start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        activo = false
        conectado = false
        hilo?.interrupt()
        super.onDestroy()
    }

    private fun bucle() {
        val hhmm = SimpleDateFormat("HH:mm", Locale.getDefault())
        var espera = 2000L
        var ultimoEstado = ""
        fun estado(t: String) {
            if (t != ultimoEstado) {
                ultimoEstado = t
                Avisos.actualizarFija(this, t)
            }
        }
        while (activo) {
            val p = Prefs(this)
            if (!p.configurado() || !p.alMomento) {
                stopSelf()
                return
            }
            try {
                val n = Comprobador.consultar(this, wait = 50, lanzar = true)
                conectado = true
                espera = 2000L
                if (n > 0) estado("Escuchando ofertas · última a las ${hhmm.format(Date())}")
                else if (!ultimoEstado.startsWith("Escuchando")) estado("Escuchando ofertas nuevas")
            } catch (e: Exception) {
                if (!activo) break
                conectado = false
                estado("Sin conexión con la Pi · reintentando (¿Tailscale activo?)")
                dormir(espera)
                espera = minOf(espera * 2, 60000L)
            }
        }
    }

    private fun dormir(ms: Long) {
        try {
            Thread.sleep(ms)
        } catch (_: InterruptedException) {
        }
    }
}
