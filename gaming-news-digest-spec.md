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
  - r/gamingleaks (rumores generales)
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

- **Motor de IA:** modelo local vía Ollama. Modelo candidato: `llama3.2:3b` o `qwen2.5:1.5b` (cuantizados, para viabilidad en CPU sin GPU).
- **Fallback opcional:** si el tiempo de ejecución en CI se dispara demasiado con el modelo local, usar Groq (API gratuita) como alternativa. Debe ser fácilmente intercambiable (mismo formato de entrada/salida).
- **Estilo de resumen:** breve (1-2 líneas), en el idioma original de la fuente (no traducir).
- **Datos generados por noticia:**
  - Resumen breve
  - Puntuación de relevancia (ej. escala 1-5)
  - Categoría: lanzamiento / actualización / rumor / análisis (u otras categorías a definir si hacen falta)

---

## 5. Ejecución y automatización

- **Frecuencia:** cada hora, mediante GitHub Actions con cron schedule.
- **Proceso por ejecución:**
  1. Rastrear todas las fuentes
  2. Filtrar según listas de inclusión/exclusión
  3. Resumir y clasificar con el modelo de IA
  4. Actualizar el/los archivo(s) de datos (JSON) que consume el frontend
  5. Commit automático de los datos actualizados al repo

---

## 6. Histórico y limpieza de datos

- No se mantiene histórico permanente completo; solo las noticias más recientes.
- Limpieza automática cuando se cumpla cualquiera de estas condiciones:
  - Han pasado 2 semanas desde la noticia más antigua almacenada, **o**
  - El número total de noticias almacenadas supera las 200
- (El criterio exacto de limpieza — por antigüedad, por cantidad, o ambos combinados — queda abierto a que la IA que implemente el proyecto proponga la lógica más sencilla y robusta).

---

## 7. Frontend / presentación web

- **Alojamiento:** GitHub Pages (repo público, sin backend propio, gratis).
- **Stack:** HTML/CSS/JS vanilla (sin frameworks pesados), que lea el JSON generado por el pipeline de Python.
- **Estilo visual:** simple pero cuidado — nada "vibecodeado" ni de aspecto genérico/plantilla básica. Debe transmitir calidad de diseño aunque sea minimalista.
- **Modo oscuro:** por defecto.
- **Funcionalidad:**
  - Filtro/búsqueda por juego, categoría y/o fecha
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
