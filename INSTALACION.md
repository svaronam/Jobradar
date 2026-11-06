# JobRadar

Busca en LinkedIn ofertas de **programador, desarrollador o analista, con cualquier lenguaje**, las puntúa de 0 a 100 según tus prioridades, te prepara **un CV adaptado a cada oferta** y te avisa en el móvil por Tailscale. De momento no se postula: tú abres la oferta, miras el CV y decides.

```
jobradar/
├── server/        → Python para la Raspberry (solo paquetes de apt, sin pip)
│   └── data/      → tu CV, las ofertas y los ajustes (no va al repo)
├── android/       → APK (se compila sola en GitHub Actions)
└── .github/workflows/apk.yml
```

## Qué busca y dónde

| Modo | Dónde | Cómo |
|---|---|---|
| Remoto | Toda España | filtro «En remoto» de LinkedIn, 3 páginas (30 ofertas) por palabra |
| Tu zona | Cantabria, y Bilbao + 40 km | híbrido y presencial en una sola búsqueda, 1 página |

Cada pasada cruza las **7 palabras clave** (`programador`, `desarrollador`, `developer`, `software engineer`, `backend`, `analista programador`, `analista funcional`) con esos 3 modos: unas 35 peticiones. Las palabras clave se editan en ⚙ Ajustes.

**La búsqueda es genérica a propósito.** Da igual el lenguaje o las herramientas que pida la oferta, porque eso lo cubre el CV adaptado: pone delante lo transferible (APIs, microservicios, SQL, batch, testing, arquitectura) sin decir que sabes lo que no sabes. Por eso no se descarta ninguna tecnología, y tu stack solo da **puntos extra**: a igualdad de lo demás, una oferta de Java sale por encima de una de .NET, pero las dos te llegan.

**La modalidad se saca de lo que dice la propia oferta, no del filtro de la búsqueda.** El filtro de remoto de la búsqueda pública de LinkedIn cuela muchas híbridas, y en zonas pequeñas ignora el de híbrido/presencial. Por eso cada oferta se clasifica así:
- **Remoto**: el título o la descripción lo dicen claro («100% remoto», «full remote», «trabajo en remoto desde…»). Visitas puntuales a la oficina no cuentan.
- **Híbrido**: habla de modelo híbrido, días de oficina, teletrabajo parcial o «posibilidad de teletrabajo X días». No cuentan «cloud híbrido», «nube híbrida» y parecidos.
- **Remoto con oficina**: dice remoto y también pide ir a la oficina.
- **Presencial**: lo dice, o la oferta es de tu zona y no dice nada.
- **Remoto sin confirmar**: salió en la búsqueda de remoto pero la oferta no dice nada. Se avisa igual, pero suma 15 puntos en vez de 30 (se cambia en ⚖ Baremo).

Las híbridas, presenciales y «remoto con oficina» que quedan a más de 80 km se filtran. El motivo **cita la frase de la oferta**, por ejemplo «Híbrido a ~427 km de Limpias · «…2 días en nuestra oficina de Madrid…»», y lo mismo sale en el desglose de puntos.

Si alguna está mal clasificada, en **Detalle → ¿La modalidad está mal?** la corriges a mano y se repuntúa al momento. Para ver de golpe cómo ha quedado todo lo que salió en la búsqueda de remoto: `python3 run.py modalidades`.

Cuando hay pocas coincidencias, LinkedIn rellena con cualquier cosa (conductores, prensa…). Esas ofertas se descartan por título como «No es un puesto de informática», sin abrirlas.

**Cuándo busca** se elige en ⚙ Ajustes → 🕑 Cuándo buscar ofertas:
- **A horas fijas**: de serie a las 08:40, 13:40 y 19:40.
- **Cada X horas** dentro de una franja, por ejemplo cada 3 h de 08:00 a 22:00. El mínimo es 1 h, porque con menos LinkedIn empieza a bloquear.
- En los dos modos puedes elegir los días, por ejemplo solo de lunes a viernes.

El cambio se aplica al momento, sin reiniciar. La app te enseña cuántas búsquedas y peticiones a LinkedIn salen al día, y la hora de la próxima búsqueda.

Si la Pi estuvo apagada, recupera la búsqueda perdida al encenderse. Cada búsqueda mira las ofertas publicadas desde la anterior: como mínimo las de las últimas 24 h y como máximo las de la última semana.

**⚡ Barrido rápido**, para postular de los primeros: cada 15 min (5-180, o 0 para desactivarlo) dentro de la franja horaria. Hace una sola búsqueda por zona con todas las palabras clave juntas (`programador OR desarrollador OR …`) y solo de lo publicado desde el barrido anterior: unas 3 peticiones más una por oferta nueva, frente a las ~35 de una búsqueda completa. Las búsquedas completas siguen a sus horas para no perderse nada. Si LinkedIn limita, los barridos rápidos se paran solos 2 h.

Para comprobar que la búsqueda con `OR` devuelve lo que toca: `python3 run.py probar --rapida`.

**Avisos al momento en el móvil**: activado por defecto en *Ajustes de la app*. Deja una notificación fija y mantiene una conexión abierta con la Pi, que contesta en cuanto una oferta nueva tiene su CV, así que el aviso llega en segundos. La notificación fija se puede ocultar desde los ajustes de notificaciones de Android sin que se pare. Si lo desactivas, queda el comprobador de respaldo cada 15-30 min (mínimo 15 por límite de Android).

Solo se abre el detalle de las ofertas **nuevas**, y antes se descartan por título las que no son de programar ni analizar (QA, comercial, soporte, prácticas, diseño…). La lista de exclusiones se edita en ⚙ Ajustes.

Lee la **búsqueda pública de LinkedIn, sin iniciar sesión**: no usa tu cuenta, así que no te la pueden restringir. Va despacio, con 3-7 s entre peticiones. Si LinkedIn empieza a limitar, la pasada se corta sola y te llega un aviso «⚠ Estado del radar».

## El baremo

| Criterio | Puntos |
|---|---|
| **Modalidad y distancia a Limpias** | remoto 30 · híbrido 25 / 22 / 18 / 12 (≤ 20, 40, 60, 80 km) · presencial 18 / 14 / 10 / 5 |
| **Puesto** | desarrollo (cualquier lenguaje, backend, frontend, full stack, móvil) y analista 20 · liderazgo o arquitectura 15 · datos 12 · otro 5 |
| **Experiencia pedida** | hasta 6 años 15 · 7-8 años 8 · más de 8 años 0 · junior 4 · sin indicar 9 |
| **Sueldo** | ≥ objetivo (45k) 15 · ≥ mínimo (35k) 10 · sin publicar 4 · **por debajo del mínimo −15** |
| **Extra: tu stack** (máx. 15) | Java 6 · Spring Boot 5 · Spring Batch 4 · SQL, microservicios y Python 3 · JPA, REST, JUnit, AWS… 2. Lo que no tienes no resta |
| **Frescura** | menos de 24 h +3 · menos de 25 candidatos +2 · más de 200 −2 |
| **Penalizaciones** | contrato temporal −5 · «remoto» que pide ir a la oficina −25 · lenguaje principal distinto 0 (actívalo en ⚖ si algún día quieres primar Java) |

Niveles: **🔴 Prioritaria ≥ 75** (suena) · **🟠 Interesante ≥ 58** · **🔵 A vigilar ≥ 40** (sin sonido) · **Baja < 40** (solo en la lista).

Estas ofertas quedan **filtradas**: se guardan, pero no se avisa de ellas.
- Híbridas o presenciales a más de 80 km.
- Ofertas «remotas» que piden ir a una oficina lejos.
- Empresas excluidas y prácticas.

En la app, toca el número de cualquier oferta para ver de dónde sale cada punto.

### Cambiar el baremo desde la app

Pulsa **⚖** (arriba, o en ⚙ → ⚖ Baremo). Ahí puedes cambiar todos los números de la tabla:
- los puntos de remoto y los **tramos de km** de híbrido y presencial (puedes añadir o quitar tramos),
- cada tipo de puesto,
- **cada tecnología** del stack y el máximo del bloque,
- experiencia, sueldo, frescura y penalizaciones,
- y los **umbrales de cada nivel**.

Lo que difiere del baremo de serie sale resaltado, con el valor de serie debajo. Arriba se ve en vivo el **máximo posible**. También avisa si un nivel queda inalcanzable, si los niveles no van de mayor a menor o si el último tramo de km es menor que tu radio.

**Guardar y recalcular** vuelve a puntuar todas las ofertas guardadas con los números nuevos y te dice cuántas cambian de nivel. Lo mismo pasa al cambiar sueldo, km o exclusiones en ⚙ Ajustes. **Volver al de serie** lo deja todo como venía.

Se guarda en `server/data/ajustes.json`. `config.json → pesos` sigue funcionando para quien prefiera editarlo a mano.

## El CV adaptado

Para cada oferta con **55 puntos o más** se genera un PDF de una página con el mismo estilo que tu CV. Va en el idioma de la oferta: tienes cargados el CV en español y en inglés.

**Qué cambia Gemini:**
- Reescribe el extracto del perfil y la línea bajo tu nombre, orientados al puesto.
- Reordena las viñetas de cada experiencia y puede reformularlas para poner delante lo que pide la oferta.
- Reordena las habilidades y las secciones.
- Marca en negrita las palabras clave de la oferta.

**Qué no puede hacer.** Lo comprueba una guarda en Python después de Gemini:
- No puede nombrar tecnologías que no estén en tu CV. Si la oferta pide Kafka y no lo tienes, no aparece en el CV: sale en la ficha como ❌ requisito no cumplido.
- No puede añadir cifras.
- No puede atribuirte cargos o liderazgo.
- No puede quitar viñetas ni habilidades.
- No puede tocar empresas, fechas, puestos ni formación.

Si una frase incumple algo de esto, se queda la tuya original. En la ficha («Detalle») ves:
- los requisitos de la oferta frente a tu CV (✅ 🟡 ❌),
- qué se ha cambiado,
- qué cambios descartó la guarda.

**Sin API key de Gemini** también funciona, pero solo reordena viñetas y habilidades según las palabras de la oferta.

**Mi CV:** ahí están tu CV en español y en inglés.
- Puedes **subir un PDF nuevo**: Gemini lo convierte en el formato que usa el bot.
- **Ver cómo lo genera el bot** muestra tu CV pintado por el generador.
- **Editar** abre el JSON por si algo no se leyó bien.

---

## Candidaturas

Cuando te postules a una oferta, pulsa **✓ Aplicada** en su tarjeta y pasa a la pestaña **Candidaturas**. Ahí:
- Cada candidatura avanza por *Aplicada → Entrevista → Prueba técnica → Oferta*, o se cierra como *Rechazada* o *Me retiré*.
- En cada paso puedes apuntar una nota (con quién hablaste, qué te preguntaron, qué sueldo comentaron…) y la fecha, por si lo apuntas días después. Si te equivocas, borras el paso y vuelve la fase anterior.
- **Recordatorio**: si una candidatura en curso lleva **7 días** sin ningún movimiento, te llega «⏰ Candidatura sin novedades», solo entre las 9 y las 21 h. Si sigues sin apuntar nada, se repite cada vez que vuelvan a pasar esos días. Los días se cambian en ⚙ Ajustes (0 = nunca).

## Resumen del día

A las **20:00** te llega una notificación con las **3 mejores ofertas** de las últimas 24 h que aún no has abierto. Si no hay ninguna, no llega nada. La hora, el número de ofertas y si lo quieres se cambian en ⚙ Ajustes, donde también hay un botón para enviar uno de prueba.

## 1 · Servidor en homelab1

Usa el puerto **8796**, que no choca con Wallapop (8787), Wallabot (8788) ni pi-agent (8790).

```bash
# en el PC: sube la carpeta server (incluye data/ con tu CV ya cargado)
scp -r jobradar/server sergio@homelab1:~/jobradar

# en la Pi
ssh sergio@homelab1
cd ~/jobradar
bash install.sh            # paquetes de apt + servicio systemd + lo enlaza en Pi Monitor
python3 run.py probar      # ¿lee LinkedIn? enseña ofertas y cómo las puntuaría, sin guardar
```

**Haz `probar` antes de nada.** El lector está escrito con el formato de la búsqueda pública de LinkedIn, pero no lo he podido probar contra la web real.
- Si sale `0 ofertas` en todos los modos, pásame `data/debug/lista_vacia.html` y lo ajusto.
- Si las descripciones salen vacías, pásame `data/debug/detalle_*.html`.

En cuanto arranca el servicio hace la primera pasada, con las ofertas de la última semana. Esas no generan avisos, para no llenarte el móvil, pero sí CV.

Desde el móvil, con Tailscale activo: `http://homelab1:8796`

```bash
journalctl -u jobradar -f           # log en vivo
python3 run.py pasada               # pasada manual (también con el botón ⟳ Buscar)
python3 run.py demo                 # 5 ofertas de ejemplo para ver la app
python3 -m unittest discover tests  # tests
```

## 2 · API key de Gemini

Puedes usar la misma que en OpoTest (Google AI Studio). Ponla en la app: **⚙ → API key de Gemini → Probar → Guardar**. Se guarda en `server/data/ajustes.json` con permisos 600.

Con el nivel gratuito sobra para unas decenas de CV al día. Entre CV hay 4 s de pausa para no pasar del límite por minuto.

## 3 · APK

1. Crea el repo `github.com/svaronam/jobradar` y sube **toda** la carpeta `jobradar/`, incluida `.github/`. `server/data/` está en `.gitignore`, así que tu CV y tus datos no se suben.
2. *(Recomendado)* Crea la clave de firma y añádela como secretos del repo (*Settings → Secrets and variables → Actions*). Sin ellos la APK compila igual, pero firmada con una clave provisional distinta en cada compilación, así que para instalar una versión nueva tendrás que desinstalar la anterior:
   ```bash
   keytool -genkeypair -v -keystore jobradar.jks -alias jobradar -keyalg RSA -keysize 2048 -validity 10000
   base64 -w0 jobradar.jks     # → secreto KEYSTORE_BASE64
   ```
   El secreto `KEYSTORE_PASSWORD` es la contraseña que hayas puesto. Guarda el `.jks` fuera del repo.
3. Actions compila la APK en cada push que toque `android/`. Descárgala desde **Releases → «ultima» → JobRadar.apk**.
4. Abre la app → servidor `http://homelab1:8796` → **Guardar** (comprueba la conexión) → **Probar aviso**.
5. Ajustes del móvil → Apps → JobRadar → Batería → **Sin restricciones**.

**Cómo llegan los avisos:**
- Cada 30 min (mínimo 15) la app pregunta a la Pi si hay ofertas nuevas.
- Una oferta no se avisa hasta que su CV está listo, así que la notificación ya lo trae.
- La notificación tiene dos botones: **Abrir en LinkedIn** y **Ver CV**.
- Si llegan más de 5 de golpe, recibes un resumen y las 4 mejores.

**En la app:**
- **📄 CV** abre el PDF.
- **⤴** lo comparte (correo, Drive, la app de LinkedIn para adjuntarlo…).
- **✓ Aplicada**, **⭐** y **✕** te sirven para llevar la cuenta.

## Ajustes útiles

- Desde la app (⚙):
  - Sueldo mínimo y objetivo, años de experiencia y km máximos.
  - Palabras clave, horas de pasada y umbral de CV.
  - Qué niveles notificar, títulos y empresas excluidos, y API key.
- Desde `server/config.json`:
  - `modos`: las zonas de búsqueda.
  - `token`: para proteger la web/API.
  - `pesos`: el baremo.

  Tras cambiarlo: `sudo systemctl restart jobradar`.
