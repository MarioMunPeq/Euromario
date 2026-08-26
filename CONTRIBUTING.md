# Guías del proyecto

Este documento define las pautas obligatorias para desarrollar G-Patch Notes: propósito, convenciones de código, contrato de datos, funcionamiento del pipeline, reglas del filtro, frontend y testing. Léelo entero antes de tocar código.

---

## 1. Propósito y restricciones clave

**Qué es:** script en Python que rastrea noticias de videojuegos (medios especializados vía RSS, Steam News API, Reddit vía RSS), filtra por relevancia personal (sagas seguidas), resume y clasifica con IA local, y publica una web estática autoactualizada en GitHub Pages.

**Objetivo:** pieza de portfolio (backend Python, scraping, CI/CD real, IA local). La calidad y el orden importan tanto como la funcionalidad.

**Restricciones innegociables:**

- **Coste económico cero.** Nada puede depender de servicios de pago.
- **Todo el cómputo corre en GitHub Actions gratuito** (runners ubuntu-latest, cron horario, job con timeout de ~55 min para no acercarse al límite de 6 h).
- **La IA es local vía Ollama** (modelo pequeño cuantizado, CPU). El fallback a Groq existe solo por rendimiento de CI, debe ser opcional (secreto `GROQ_API_KEY`) y fácilmente intercambiable: misma interfaz, misma entrada/salida.
- **Idiomas de fuente:** español e inglés aceptados tal cual; el resumen se genera en el idioma original, nunca se traduce.
- **Reddit siempre se marca como categoría aparte** ("Reddit / Rumores"): es contenido no verificado de comunidad y debe distinguirse visualmente de las noticias de medios oficiales.

---

## 2. Estructura del repositorio

```text
├── .github/workflows/
│   ├── digest.yml              # Pipeline horario: fetch → IA → commit de datos
│   └── deploy-pages.yml        # Despliegue del frontend en GitHub Pages
├── config/
│   ├── games.yaml              # Listas de inclusión/exclusión de juegos (editar a mano)
│   └── sources.yaml            # Fuentes: feeds RSS, app_ids de Steam, subreddits, límites
├── src/gaming_news_digest/     # Paquete principal (src layout)
│   ├── __main__.py             # CLI: python -m gaming_news_digest
│   ├── config.py               # Carga y validación de los YAML
│   ├── models.py               # Modelos de dominio (NewsItem, Source, FetchedItem)
│   ├── pipeline.py             # Orquestador de las 5 fases
│   ├── fetchers/               # rss.py, steam.py, reddit.py + base.py compartido
│   ├── filtering/              # matcher.py (inclusión/exclusión robusto)
│   ├── ai/                     # base.py (interfaz común), ollama_client.py, groq_client.py
│   └── storage/                # json_store.py, retention.py (histórico)
├── tests/                      # pytest (sin red, fixtures locales)
├── frontend/                   # Lo único que publica GitHub Pages
│   ├── index.html
│   ├── css/style.css
│   ├── js/app.js
│   └── data/news.json          # Generado por el pipeline; versionado a propósito
├── requirements.txt
├── CONTRIBUTING.md
└── README.md
```

Reglas estructurales:

- Todo el Python vive en `src/gaming_news_digest/` (src layout). Los tests nunca importan el paquete por rutas relativas raras; se usa `PYTHONPATH=src`.
- La configuración vive **siempre** en `config/*.yaml`. Prohibido hardcodear URLs, nombres de juegos o límites en código.
- El único punto de entrada es `python -m gaming_news_digest`.

---

## 3. Convenciones de código

- **Estilo:** PEP 8 verificado con `ruff check src tests` (configuración por defecto). Debe pasar limpio antes de cualquier push.
- **Type hints:** obligatorios en todas las funciones públicas y firmas de dataclasses.
- **Idiomas:** identificadores y nombres de símbolos en inglés (`fetch_feed`, `NewsItem`); docstrings, comentarios y mensajes de error/commit en español.
- **Naming:** módulos y funciones `snake_case`, clases `PascalCase`, constantes `UPPER_SNAKE`, privados con `_` inicial. Módulos en singular (`matcher.py`, no `matchers.py`).
- **Organización:** un módulo = una responsabilidad. Sin lógica de negocio en los `__init__.py`. El orquestador (`pipeline.py`) no implementa detalles: delega en fetchers/filtro/IA/storage.
- **Robustez:** una fuente caída o un item corrupto nunca deben tumbar la ejecución completa; se registra el error y se continúa. Excepciones específicas del dominio, no `except Exception` silenciosos.
- **Commits:** Conventional Commits con tipo en inglés y descripción en español minúscula: `feat: añadir fetcher de steam`, `fix(corretja): ...`. Ramas cortas estilo trunk-based: `feat/nombre-corto`.
- **Determinismo:** el pipeline debe ser idempotente; ejecutarlo dos veces sin fuentes nuevas no produce diffs.

---

## 4. Contrato de datos: `frontend/data/news.json`

Es el único archivo que consumen frontend y backend en común. Cambiar su schema exige actualizar **a la vez** este documento, `storage/json_store.py` y el render del frontend.

```json
{
  "generated_at": "2026-08-23T12:04:31Z",
  "total": 42,
  "news": [
    {
      "id": "9f2c1ab77e04d3c8",
      "title": "Persona 6 muestra primer tráiler",
      "summary": "Atlus adelanta el primer tráiler y ventana de lanzamiento.",
      "url": "https://www.eurogamer.net/...",
      "source": { "name": "Eurogamer", "type": "media", "subreddit": null },
      "game": "Persona",
      "language": "en",
      "published_at": "2026-08-23T09:15:00Z",
      "relevance": 5,
      "category": "lanzamiento",
      "image_url": "https://cdn.example.com/persona6.jpg"
    }
  ]
}
```

Invariantes:

- Claves en inglés; valores de enums en español ASCII (sin tildes, para URLs/comparaciones seguras).
- `id`: hex de 16 caracteres = primeros 16 bytes de `sha256(url normalizada)`. Estable entre ejecuciones (base del dedup).
- `source.type`: `"media"` | `"steam"` | `"reddit"`. Si es `"reddit"`, `subreddit` no es null y el frontend lo muestra como "Reddit / Rumores".
- `category`: `"lanzamiento"` | `"actualizacion"` | `"rumor"` | `"analisis"`.
- `relevance`: entero 1–5 asignado por la IA (5 = anuncio mayor de una saga seguida; 1 = mención menor).
- `language`: `"es"` o `"en"`; `summary` va en ese mismo idioma.
- `image_url`: URL http(s) válida o `null` (cuando no se encontró imagen destacada en el feed).
- Todos los timestamps en UTC ISO-8601 con sufijo `Z`.
- `news` ordenada por `published_at` descendente. `total == len(news)`.

---

## 5. El pipeline paso a paso

Ejecutado cada hora por `.github/workflows/digest.yml` (y manualmente con `python -m gaming_news_digest`):

1. **Fetch** — `fetchers/` descarga todas las fuentes declaradas en `config/sources.yaml` (RSS de medios, Steam News por `app_id`, RSS de subreddits). Cada item se normaliza a `NewsItem` y se deduplica por `id` contra lo ya almacenado.
2. **Filtrado** — `filtering/matcher.py` aplica `config/games.yaml`: entra la noticia que matchea algún juego de inclusión y ninguno de exclusión (la exclusión gana siempre; ver sección 6).
3. **Resumen y clasificación IA** — `ai/` genera por noticia: `summary`, `relevance` y `category`. Motor por defecto: Ollama local (`ollama_client.py`). Fallback: si Ollama no está disponible, supera el timeout por ítem o acumula demasiados errores, `groq_client.py` asume el resto de la ejecución (misma interfaz definida en `base.py`). Respuestas inválidas → reintento simple → si persiste, la noticia entra sin `summary` (`null`) pero nunca bloquea el pipeline.
4. **Retención** — `storage/retention.py` limpia el histórico cuando se cumple **cualquiera** de: la noticia más antigua supera **14 días**, o el total supera **200 noticias** (recorte eliminando primero las más antiguas). Ambas condiciones combinadas, evaluadas tras cada merge.
5. **Escritura atómica y commit** — si el JSON resultante difiere del actual, se escribe de forma atómica en `frontend/data/news.json` y el workflow hace commit con el bot `github-actions[bot]` (`chore(datos): actualizar digest automático`). Ese commit toca `frontend/**`, así que dispara automáticamente el redeploy en Pages. Sin cambios → sin commit.

### Manejo de fechas en los fetchers

Los feeds reales llegan con fechas ausentes, malformadas o de fuentes con el reloj desajustado. Política implementada en `fetchers/base.py::resolve_date` y cubierta por tests:

1. **Cadena de fallback:** `published` → `updated` → **ahora (UTC)**. Nunca se descarta una noticia por su fecha: perder contenido real por metadatos rotos es peor que una fecha aproximada.
2. **Clamp anti-reloj adelantado:** una fecha más de **24 horas** en el futuro se recorta a «ahora», para que no rompa el orden descendente del JSON.
3. **Steam:** su campo `date` (epoch Unix) se convierte a UTC; valores ausentes, no numéricos o ≤ 0 caen en la misma cadena de fallback.
4. feedparser entrega las fechas ya interpretadas como `struct_time` en UTC; cualquier formato que no pueda interpretar llega como ausente y activa el punto 1.

Por la misma regla de robustez: una fuente caída (HTTP ≠ 200, timeout, JSON inválido) eleva `FetchError`, el pipeline la registra y continúa con el resto. En Steam el fallo es por app: si fallan todas se eleva el error; si falla una, se sigue con las demás.

---

### Filtro de inclusión/exclusión: prioridad de exclusión ("poison pill")

El matcher (`filtering/matcher.py`) aplica reglas estrictas para evitar ruido:

1. **Exclusión = "poison pill" global.** Si **cualquier** juego de la lista de exclusión aparece **una sola vez** en el artículo (título o body), el artículo completo se descarta, **incluso si también menciona juegos de la lista de inclusión como tema principal**. Un falso negativo en exclusión (ver FIFA cuando no quieres verlo) es peor que perder una noticia válida que casualmente menciona un juego excluido.
2. **Inclusión exige "tema principal".** Un juego de la lista de inclusión solo hace entrar el artículo si aparece en el **título** O se menciona **≥2 veces en el body**. Una sola mención en el body sin título no basta.
3. **Normalización robusta:** NFD + quita diacríticos + lowercase; límites de palabra (`\b`); aliases y variantes numéricas/romanas vienen de `config/games.yaml`.

La decisión de que la exclusión "envenene" el artículo completo (en lugar de solo ignorar el juego excluido y aceptar por el incluido) es deliberada: la lista de inclusión es amplia y genera ruido cruzado; la exclusión es blacklist deliberada y debe ganar siempre.

---

### Pipeline de IA: fallback Ollama → Groq y manejo de errores

El pipeline (`pipeline.py`) orquesta la IA con una política de resiliencia clara:

| Situación | Comportamiento |
|-----------|----------------|
| Ollama `AIError` (validación) | Fallback seguro para ese item (`summary=None, relevance=1, category="rumor"`) + pipeline continúa. Contador consecutivo +1. |
| Ollama infra (ConnectionError, Timeout, HTTP ≥500) | **Switch inmediato a Groq** y **reintenta el mismo item** con Groq. Contador a 0. |
| Groq `AIError` (validación) | **Fallback seguro para ese item** + pipeline continúa (no aborta). |
| Groq infra (ConnectionError, Timeout, HTTP ≥500) | **Crítico**: guarda en JSON lo ya procesado (items con resumen + fallbacks seguros) y aborta con error (commit parcial). |
| 3 `AIError` consecutivos en Ollama | Switch a Groq **antes del siguiente item**; el item que causó el 3er fallo se reintenta con Groq. |

> **Fallo crítico tras fallback**  
> Si Groq falla con error de infraestructura tras el fallback, el pipeline **guarda lo procesado hasta ese momento** (items con resumen válido + items con fallback seguro) y termina con error. No se descarta el trabajo ya hecho.

> **AIError en Groq tras fallback**  
> Un `AIError` de Groq (fallo de validación tras reintentos) **no aborta** el pipeline: el item recibe fallback seguro y el pipeline continúa con el siguiente. Solo errores de infraestructura (conexión, timeout, HTTP 5xx) son críticos en Groq.

Detalles de CI: `concurrency.group: digest` para evitar solapes entre ejecuciones; el modelo de Ollama se instala en el runner en cada ejecución (`ollama pull "$OLLAMA_MODEL"`).

---

## 6. Reglas del filtro de inclusión/exclusión

**Dónde vive:** `config/games.yaml`. Dos listas: `incluir` y `excluir`. Cada entrada tiene `nombre` canónico y `aliases` opcionales (abreviaturas, secuelas, nombres alternativos):

```yaml
incluir:
  - nombre: Grand Theft Auto
    aliases: [GTA]
excluir:
  - nombre: EA Sports FC
    aliases: [FIFA]
```

**Cómo se edita:** editando el YAML a mano y haciendo commit. No se toca código ni se reinicia nada: la siguiente ejecución horaria ya usa la lista nueva. Es la forma prevista de mantener el proyecto día a día.

**Semántica:**

- Una noticia entra si matchea **al menos un** juego de `incluir` y **ninguno** de `excluir`.
- **La exclusión tiene prioridad sobre la inclusión.** Si la noticia trata principalmente de un juego excluido, no se muestra aunque también mencione una saga seguida. Motivo: la lista de inclusión es amplia y generará ruido cruzado; la lista de exclusión es una blacklist deliberada y debe ganar siempre (ej. una comparativa "EA Sports FC vs eFootball" donde se menciona Persona no debe entrar).
- Se evalúa como **tema principal**, no mención casual: heurística basada en aparición en título y/o peso en el cuerpo. La heurística concreta vive en `matcher.py` y es territorio de tests obligatorios.

**Robustez exigida al matcher** (prohibido el naive `if palabra in texto`):

- Límites de palabra: "GTA" no puede matchear dentro de otra palabra.
- Alias y variantes: abreviaturas (`CoD`), numeraciones romanas/arábigas de secuelas (`GTA VI` ≡ `GTA 6`), subtítulos.
- Insensible a mayúsculas/minúsculas y acentos.
- Reddit pasa por el mismo filtro; su distinción visual viene de `source.type`, no del filtro.

---

## 7. Convenciones de frontend

- **Vanilla total:** HTML/CSS/JS sin frameworks, sin build step, sin bundler, sin CDNs externos (tipografía system-ui, iconografía inline/CSS). Tres archivos: `index.html`, `css/style.css`, `js/app.js`.
- **Modo oscuro por defecto:** `color-scheme: dark` y paleta oscura en `:root` con custom properties (`--bg`, `--surface`, `--text`, `--accent`...). Un toggle claro es opcional a futuro, nunca al revés.
- **Datos:** un único `fetch("data/news.json")` relativo y render cliente. Sin estado global complejo ni persistencia más allá de lo justo.
- **Funcionalidad mínima:** búsqueda/filtrado cliente por juego, categoría y fecha; mostrar `summary`, `relevance` (1–5) y `category` por tarjeta.
- **Reddit distinguible siempre:** badge propio tipo "Reddit · no verificado" en cada card cuyo `source.type === "reddit"`.
- **Calidad:** HTML semántico, contraste AA, focus visible, responsive mobile-first. Simple pero cuidado: nada de aspecto de plantilla genérica.
- CSS con clases coherentes y planas (kebab-case); JS en modo estricto, funciones puras para filtrar/renderizar (testeables mentalmente), sin dependencias.

---

## 8. Testing mínimo obligatorio (pytest)

Sin red: los fetchers se testean con fixtures locales (XML/HTML/JSON guardados en `tests/fixtures/`). Los clientes de IA se testean con mocks. Mínimo cubierto:

1. **Matcher** — positivos por nombre y alias; negativos; falsos positivos por subcadena ("gta" dentro de otras palabras); variantes de secuelas (VI/6); prioridad de exclusión sobre inclusión; detección de tema principal vs mención.
2. **Retención** — recorte por antigüedad (14 días), por cantidad (cap 200), combinados, y casos borde exactamente en el límite.
3. **`json_store`** — schema válido, orden descendente, id estable y determinista, escritura atómica, no-reescritura si no hay cambios.
4. **`config`** — carga correcta de YAML válidos y errores claros ante YAML inválido o incompleto.
5. **Clientes IA (mockeados)** — parseo de respuesta válida, rechazo de respuesta malformada, y activación del fallback Groq ante fallos/timeout de Ollama.
6. **Fetchers** — parseo de fixtures reales de feed RSS, respuesta Steam y RSS de Reddit; tolerancia a items incompletos; cadena de fechas (published → updated → ahora) y clamp de futuro.

Cobertura objetivo: ≥ 90 % en los módulos críticos (`matcher`, `retention`, `json_store`); resto, razonable sin obsesión.

Antes de pushear: `pytest` verde y `ruff check src tests` limpio. Si cambia el contrato de datos o una regla de este documento, actualiza `CONTRIBUTING.md` en el mismo PR.
