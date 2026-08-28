# Gaming News Digest — Especificación del Proyecto

## 1. Resumen del proyecto

Script en Python que rastrea noticias de videojuegos de múltiples fuentes (medios especializados, Steam, Reddit), las filtra por relevancia personal (juegos/sagas seguidos), las resume y clasifica usando un modelo de IA local, y publica el resultado como una página web estática autoactualizada, alojada gratuitamente en GitHub Pages.

**Objetivo del proyecto:** pieza de portfolio que demuestre backend en Python, scraping, automatización con CI/CD, e inferencia de IA local (sin depender de APIs de pago), con un frontend simple pero cuidado.

**Restricción clave:** coste económico cero. Todo debe correr con herramientas gratuitas (GitHub Actions gratuito, modelo de IA local, GitHub Pages).

---

## 2. Fuentes de datos

- **Medios especializados** (vía RSS): IGN, Eurogamer, PC Gamer, Polygon, Rock Paper Shotgun (y cualquier otro medio relevante con RSS disponible)
- **Steam News**: noticias/actualizaciones oficiales de juegos vía Steam News API
- **Reddit** (vía RSS de subreddits):
  - r/gamingleaksandrumours (rumores generales)
  - Subreddits específicos de sagas seguidas, cuando existan y tengan actividad relevante
  - **Importante:** el contenido de Reddit debe mostrarse/marcarse visualmente como una categoría aparte ("Reddit / Rumores"), diferenciada de las noticias de medios oficiales, dejando claro al lector que es contenido no verificado de comunidad.
- **Idiomas de fuente:** español e inglés, ambos aceptados sin traducir (el resumen se genera en el idioma original de la noticia).

---

## 3. Filtrado de contenido

- **Lista de inclusión:** lista amplia y extensa de juegos/sagas famosas a seguir (ej. Call of Duty, GTA, Persona, y muchos más — pendiente de definir la lista completa).
- **Lista de exclusión:** juegos concretos que NO se quieren ver nunca, aunque aparezcan en las fuentes (ej. FIFA/EA Sports FC).
- **Comportamiento del filtro:** debe ser un filtro robusto — se prioriza que sea preciso y bien pensado, no un simple `if palabra in texto`. Debe evitar falsos positivos (ej. que "GTA" no matchee con palabras que la contengan por casualidad) y falsos negativos (variantes de nombres, secuelas, abreviaturas comunes).
- La exclusión tiene prioridad sobre la inclusión: si una noticia menciona un juego excluido como tema principal, no se muestra, incluso si también menciona un juego de la lista de seguimiento.

---

## 4. Resumen y clasificación (IA)

- **Motor de IA:** modelo local vía Ollama. Modelo configurado: `llama3.2:3b` (cuantizado, CPU-only en CI).
- **Fallback opcional:** Groq (API gratuita) como alternativa de rendimiento en CI. Requiere la variable de entorno `GROQ_API_KEY` (no se carga ningún archivo `.env` automáticamente; la variable debe exportarse en la shell o configurarse como secreto de GitHub Actions). La interfaz de entrada/salida es idéntica (definida en `ai/base.py`), lo que permite el intercambio transparente.
- **Estilo de resumen:** breve (1-2 líneas), en el idioma original de la fuente (no traducir).
- **Datos generados por noticia:**
  - Resumen breve
  - Puntuación de relevancia (ej. escala 1-5)
  - Categoría: lanzamiento / actualización / rumor / análisis (u otras categorías a definir si hacen falta)

---

## 5. Ejecución y automatización

- **Frecuencia:** cada hora, mediante GitHub Actions con cron schedule.
- **Proceso por ejecución:**
  1. **Fetch** — rastrear todas las fuentes (RSS medios, Steam News API, RSS Reddit)
  2. **Filtrado** — aplicar listas de inclusión/exclusión (`config/games.yaml`)
  3. **Clustering** — agrupar items duplicados por juego
  4. **Límite por juego (pre-IA)** — aplicar `max_stories_por_juego` (default 8) antes de la IA para evitar llamadas innecesarias; orden por `relevance` (si existe) y `published_at` descendente
  5. **IA** — resumir y clasificar solo los items que pasan el pre-límite (Ollama → fallback Groq)
  6. **Límite por juego (post-IA)** — re-aplicar el mismo límite tras la IA usando `relevance` + `published_at`
  7. **Retención** — limpiar histórico: `max_age_hours=48` (corte inclusivo: `published_at >= now - 48h`) y `max_total=200`
  8. **Escritura atómica y commit** — si el JSON difiere, escribir `frontend/data/news.json` y commit automático

---

## 6. Histórico y limpieza de datos (retención)

- No se mantiene histórico permanente completo; solo las noticias más recientes dentro de la ventana de retención.
- Limpieza automática (`storage/retention.py::apply_retention`) cuando se cumpla **cualquiera** de estas condiciones (evaluadas en orden combinado):
  - **Antigüedad:** la noticia más antigua supera **48 horas** (corte inclusivo: se conserva si `published_at >= now - 48h`; se elimina si `published_at < now - 48h`).
  - **Cantidad:** el total de noticias almacenadas supera **200** (recorte eliminando primero las más antiguas).
- Parámetros canónicos: `max_age_hours: int = 48`, `max_total: int = 200`. Ambos límites operan juntos; no se mantiene nada fuera de la ventana de 48h ni por encima de 200 items totales.

---

## 7. Frontend / presentación web

- **Alojamiento:** GitHub Pages (repo público, sin backend propio, gratis).
- **Stack:** HTML/CSS/JS vanilla (sin frameworks pesados), que lea el JSON generado por el pipeline de Python.
- **Estilo visual:** simple pero cuidado — nada "vibecodeado" ni de aspecto genérico/plantilla básica. Debe transmitir calidad de diseño aunque sea minimalista.
- **Modo oscuro:** por defecto.
- **Funcionalidad:**
  - Filtro por juego, categoría y plataforma (NEWS / RUMORS)
  - Distinción visual clara entre noticias de medios oficiales y contenido de Reddit
  - Mostrar resumen, puntuación de relevancia y categoría por noticia

---

## 8. Stack técnico (resumen)

| Componente | Tecnología |
|---|---|
| Lenguaje principal | Python |
| Scraping/RSS | `feedparser`, `requests`, `BeautifulSoup` |
| IA / resumen | Ollama (modelo local pequeño), fallback Groq API |
| Tests | `pytest` |
| Automatización | GitHub Actions (cron horario) |
| Almacenamiento de datos | JSON plano en el propio repo |
| Frontend | HTML/CSS/JS vanilla |
| Hosting | GitHub Pages |

---

## 9. Objetivos de portfolio (contexto para la IA que lo implemente)

Este proyecto busca complementar otros proyectos ya existentes del autor (una web de fandom en React/TypeScript y una app de gestión de campañas de D&D en FastAPI), aportando:

- Un proyecto mayoritariamente en Python (para diversificar el stack mostrado)
- Demostración de automatización real vía CI/CD (GitHub Actions)
- Demostración de inferencia de IA local, sin depender de APIs de pago
- Testing con `pytest`
- Un producto final visitable con un solo link, sin coste de hosting

## 10. Pendiente de definir

- Lista completa y definitiva de juegos/sagas a seguir e (lista de inclusión)
- Lista completa de juegos a excluir
- Nombre final del repositorio
- Lista definitiva de fuentes RSS concretas (URLs exactas)
