package com.svaronam.jobradar

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.FileProvider
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * La app es una ventana a la web que sirve la Pi (la misma interfaz que en el navegador) más los avisos en
 * segundo plano. Así cualquier mejora en el servidor llega al móvil sin recompilar la APK.
 * Añade lo que una WebView no hace sola: abrir y compartir el PDF del CV y elegir un archivo para subir.
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var prefs: Prefs
    private var eligiendo: ValueCallback<Array<Uri>>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        Avisos.crearCanales(this)

        web = WebView(this).apply {
            layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.setSupportMultipleWindows(false)
            addJavascriptInterface(Puente(), "Android")
            webViewClient = Cliente()
            webChromeClient = Chrome()
        }
        web.setBackgroundColor(Color.parseColor("#0B1118"))  // sin destello blanco mientras carga
        setContentView(web)
        barras(true)

        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }

        if (prefs.configurado()) {
            Comprobador.programar(this)
            Servicio.arrancar(this)
            cargar(intent)
        } else {
            web.loadDataWithBaseURL(null, paginaInicio(), "text/html", "utf-8", null)
            ajustes()
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (prefs.configurado()) cargar(intent)
    }

    private fun cargar(i: Intent?) {
        val a = i?.getStringExtra("ancla") ?: ""
        web.loadUrl(prefs.url("/") + if (a.isNotBlank()) "#$a" else "")
        // botón "Ver CV" de la notificación
        val cvId = i?.getLongExtra("cv_id", 0L) ?: 0L
        if (cvId > 0) {
            i?.removeExtra("cv_id")
            descargar(prefs.url("/api/ofertas/$cvId/cv.pdf"), "CV_oferta_$cvId.pdf", compartir = false)
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    // ------------------------------------------------------------------ PDF
    /** Baja el PDF a la caché de la app y lo abre (o lo comparte: correo, Drive, LinkedIn...). */
    private fun descargar(url: String, nombre: String, compartir: Boolean) {
        Toast.makeText(this, "Descargando CV…", Toast.LENGTH_SHORT).show()
        Thread {
            try {
                val dir = File(cacheDir, "cvs").apply { mkdirs() }
                val limpio = nombre.replace(Regex("[^A-Za-z0-9._-]"), "_").ifBlank { "cv.pdf" }
                val f = File(dir, if (limpio.endsWith(".pdf")) limpio else "$limpio.pdf")
                val c = URL(url).openConnection() as HttpURLConnection
                c.connectTimeout = 15000
                c.readTimeout = 30000
                if (prefs.token.isNotBlank()) c.setRequestProperty("X-Token", prefs.token)
                try {
                    if (c.responseCode != 200) throw IllegalStateException("HTTP ${c.responseCode}")
                    c.inputStream.use { ins -> f.outputStream().use { ins.copyTo(it) } }
                } finally {
                    c.disconnect()
                }
                val uri = FileProvider.getUriForFile(this, "$packageName.archivos", f)
                runOnUiThread {
                    val i = if (compartir) {
                        Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
                            type = "application/pdf"
                            putExtra(Intent.EXTRA_STREAM, uri)
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        }, "Compartir CV")
                    } else {
                        Intent(Intent.ACTION_VIEW).apply {
                            setDataAndType(uri, "application/pdf")
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        }
                    }
                    try {
                        startActivity(i)
                    } catch (e: ActivityNotFoundException) {
                        Toast.makeText(this, "No tienes ninguna app para abrir PDF", Toast.LENGTH_LONG).show()
                    }
                }
            } catch (e: Exception) {
                runOnUiThread {
                    Toast.makeText(this, "No pude bajar el CV: ${e.message ?: e.javaClass.simpleName}", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }

    @Suppress("DEPRECATION")
    private fun barras(oscuro: Boolean) {
        val color = Color.parseColor(if (oscuro) "#0B1118" else "#F4F1EA")
        window.statusBarColor = color
        window.navigationBarColor = color
        var f = window.decorView.systemUiVisibility
        f = if (oscuro) f and View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR.inv() else f or View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
        if (Build.VERSION.SDK_INT >= 26) {
            f = if (oscuro) f and View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR.inv() else f or View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        }
        window.decorView.systemUiVisibility = f
    }

    private fun abrirFuera(url: String) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (e: Exception) {
            Toast.makeText(this, "No se pudo abrir el enlace", Toast.LENGTH_SHORT).show()
        }
    }

    // ------------------------------------------------------------------ subir archivo (input type=file)
    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == ELEGIR) {
            val uri = if (resultCode == RESULT_OK) data?.data else null
            eligiendo?.onReceiveValue(if (uri != null) arrayOf(uri) else null)
            eligiendo = null
        }
    }

    inner class Chrome : WebChromeClient() {
        override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>,
                                       params: FileChooserParams): Boolean {
            eligiendo?.onReceiveValue(null)
            eligiendo = callback
            val i = Intent(Intent.ACTION_GET_CONTENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/pdf"
            }
            return try {
                @Suppress("DEPRECATION")
                startActivityForResult(Intent.createChooser(i, "Elige tu CV en PDF"), ELEGIR)
                true
            } catch (e: Exception) {
                eligiendo = null
                false
            }
        }
    }

    // ------------------------------------------------------------------ ajustes
    private fun ajustes() {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val caja = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad / 2, pad, 0)
        }
        fun etiqueta(t: String) = TextView(this).apply { text = t; setPadding(0, pad / 2, 0, 0) }
        val url = EditText(this).apply {
            hint = "http://homelab1:8796"
            setText(prefs.servidor.ifBlank { "http://homelab1:8796" })
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
        }
        val token = EditText(this).apply {
            hint = "(vacío si no pusiste token)"
            setText(prefs.token)
            setSingleLine(true)
        }
        val minutos = EditText(this).apply {
            setText(prefs.minutos.toString())
            inputType = InputType.TYPE_CLASS_NUMBER
            setSingleLine(true)
        }
        val alMomento = CheckBox(this).apply {
            text = "Avisos al momento (deja una notificación fija; recomendado para postular de los primeros)"
            isChecked = prefs.alMomento
            setPadding(0, pad / 2, 0, 0)
        }
        val estado = TextView(this).apply {
            text = "Última comprobación: " + prefs.ultimaConsulta.ifBlank { "—" } +
                if (Servicio.conectado) "\nAvisos al momento: conectado" else ""
            setPadding(0, pad / 2, 0, 0)
            alpha = 0.7f
        }
        caja.addView(etiqueta("Servidor en la Raspberry (por Tailscale)"))
        caja.addView(url)
        caja.addView(etiqueta("Token"))
        caja.addView(token)
        caja.addView(alMomento)
        caja.addView(etiqueta("Respaldo: comprobar cada (minutos, mínimo 15)"))
        caja.addView(minutos)
        caja.addView(estado)

        val d = AlertDialog.Builder(this)
            .setTitle("JobRadar")
            .setView(caja)
            .setPositiveButton("Guardar", null)
            .setNeutralButton("Probar aviso", null)
            .setNegativeButton("Cerrar", null)
            .create()
        d.setOnShowListener {
            d.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val u = url.text.toString().trim().let { if (it.startsWith("http")) it else "http://$it" }
                prefs.servidor = u
                prefs.token = token.text.toString()
                prefs.minutos = (minutos.text.toString().toIntOrNull() ?: 30).coerceAtLeast(15)
                prefs.alMomento = alMomento.isChecked
                comprobarConexion(d)
            }
            d.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener {
                Avisos.prueba(this)
                Comprobador.ahora(this)
            }
        }
        d.show()
    }

    private fun comprobarConexion(d: AlertDialog) {
        Thread {
            val r = try {
                val j = Comprobador.get(prefs.servidor + "/api/estado", prefs.token)
                "OK · servidor " + j.optString("version")
            } catch (e: Exception) {
                "ERROR: " + (e.message ?: e.javaClass.simpleName)
            }
            runOnUiThread {
                if (r.startsWith("OK")) {
                    Toast.makeText(this, "Conectado ($r)", Toast.LENGTH_SHORT).show()
                    Comprobador.programar(this, reemplazar = true)
                    if (prefs.alMomento) Servicio.reiniciar(this) else Servicio.parar(this)
                    d.dismiss()
                    cargar(null)
                } else {
                    Toast.makeText(this, "No llego a la Pi. ¿Tailscale activo? $r", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }

    // ------------------------------------------------------------------ web
    inner class Puente {
        @JavascriptInterface
        fun openSettings() = runOnUiThread { ajustes() }

        @JavascriptInterface
        fun checkNow() = runOnUiThread { Comprobador.ahora(this@MainActivity) }

        @JavascriptInterface
        fun abrirPdf(url: String, nombre: String) = runOnUiThread { descargar(url, nombre, compartir = false) }

        @JavascriptInterface
        fun compartirPdf(url: String, nombre: String) = runOnUiThread { descargar(url, nombre, compartir = true) }

        @JavascriptInterface
        fun abrirFuera(url: String) = runOnUiThread { this@MainActivity.abrirFuera(url) }

        /** La web avisa de su tema para poner la barra de estado y la de navegación a juego. */
        @JavascriptInterface
        fun tema(oscuro: Boolean) = runOnUiThread { barras(oscuro) }
    }

    inner class Cliente : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
            val host = Uri.parse(prefs.servidor).host
            if (req.url.host == host) return false
            abrirFuera(req.url.toString())  // LinkedIn y demás: fuera (app de LinkedIn o navegador)
            return true
        }

        override fun onReceivedError(view: WebView, req: WebResourceRequest, err: WebResourceError) {
            if (req.isForMainFrame) {
                view.loadDataWithBaseURL(null, paginaError(err.description?.toString() ?: ""), "text/html", "utf-8", null)
            }
        }
    }

    private fun paginaInicio() = """
        <html><body style="font-family:sans-serif;background:#0b1118;color:#e8e4da;padding:28px">
        <h2>Job<span style="color:#6ea8fe">Radar</span></h2>
        <p>Pon la dirección del servidor de tu Raspberry (por Tailscale), p. ej. <b>http://homelab1:8796</b>.</p>
        <button onclick="Android.openSettings()" style="padding:10px 16px;border-radius:10px;border:0">Ajustes</button>
        </body></html>""".trimIndent()

    private fun paginaError(msg: String) = """
        <html><body style="font-family:sans-serif;background:#0b1118;color:#e8e4da;padding:28px">
        <h2>No llego a la Raspberry</h2>
        <p style="opacity:.75">$msg</p>
        <p>Comprueba que Tailscale está activo en el móvil y que el servicio <code>jobradar</code> corre en la Pi.</p>
        <button onclick="location.href='${prefs.url("/")}'" style="padding:10px 16px;border-radius:10px;border:0">Reintentar</button>
        <button onclick="Android.openSettings()" style="padding:10px 16px;border-radius:10px;border:0">Ajustes</button>
        </body></html>""".trimIndent()

    companion object {
        private const val ELEGIR = 42
    }
}
