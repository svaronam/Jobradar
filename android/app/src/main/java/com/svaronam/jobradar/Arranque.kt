package com.svaronam.jobradar

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Vuelve a poner en marcha los avisos al momento al encender el móvil o al actualizar la app. */
class Arranque : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED || intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            try {
                Servicio.arrancar(ctx)
            } catch (_: Exception) {
            }
        }
    }
}
