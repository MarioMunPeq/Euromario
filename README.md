# G-Patch Notes

Digest automático de noticias de videojuegos: un pipeline en Python rastrea medios especializados, Steam y Reddit cada hora, filtra las noticias según las sagas que sigo, las resume y clasifica con un modelo de IA local, y publica el resultado como una web estática autoactualizada en GitHub Pages.

> Estado: 🚧 en construcción — esqueleto del repositorio. La implementación se está haciendo módulo a módulo.
>
> Nombre final del repositorio pendiente de confirmar (ver especificación, sección 10).

## Características

- **Multi-fuente**: RSS de medios (IGN, Eurogamer, PC Gamer...), Steam News API y Reddit vía RSS (marcado aparte como "Reddit / Rumores", contenido no verificado).
- **Filtro personal**: solo noticias de juegos/sagas seguidos, con lista de exclusión prioritaria.
- **IA local**: resumen breve y clasificación con Ollama (`llama3.2:3b` cuantizado, CPU), con fallback a Groq (API gratuita) si el runtime de CI se dispara.
- **Coste cero**: todo corre en GitHub Actions gratuito + GitHub Pages. Sin servidores, sin APIs de pago.
- **Histórico con retención**: máximo 2 semanas / 200 noticias, limpieza automática.
- **Frontend cuidado**: HTML/CSS/JS vanilla, modo oscuro por defecto, búsqueda por juego/categoría/fecha.

## Stack

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.12 |
| Scraping/RSS | `feedparser`, `requests`, `BeautifulSoup` |
| IA | Ollama (local) · Groq como fallback |
| Config | YAML editable a mano |
| Tests | `pytest` (+ `ruff` para linting) |
| CI/CD | GitHub Actions (cron horario) |
| Datos | JSON plano versionado en el repo |
| Frontend | HTML/CSS/JS vanilla |
| Hosting | GitHub Pages |

## Ejecución local

Requisitos previos:

- Python 3.11+ (en CI se usa 3.12)
- [Ollama](https://ollama.com) instalado y el modelo descargado:
  ```powershell
  ollama pull llama3.2:3b
  ```

Pasos:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:PYTHONPATH = "src"
$env:OLLAMA_MODEL = "llama3.2:3b"        # opcional, este es el valor por defecto
$env:GROQ_API_KEY = "..."                # opcional, solo si quieres probar el fallback
python -m gaming_news_digest
```

En bash/Linux/macOS, activa el venv con `source .venv/bin/activate` y exporta las variables con `export`.

Tests y linting:

```powershell
pytest
ruff check src tests
```

## Cómo funciona

1. **Fetch** — se rastrean todas las fuentes (RSS medios, Steam, Reddit).
2. **Filtrado** — inclusión/exclusión según `config/games.yaml`; la exclusión tiene prioridad.
3. **IA** — cada noticia se resume (1-2 líneas, idioma original) y clasifica (lanzamiento/actualización/rumor/análisis) + puntuación de relevancia 1-5.
4. **Retención** — se limpia el histórico (>14 días o >200 noticias).
5. **Commit** — si hay cambios, el bot los sube; eso dispara el despliegue en Pages.

Las reglas completas del proyecto están documentadas en [CONTRIBUTING.md](CONTRIBUTING.md).

## Demo

🚧 Pendiente del primer despliegue. URL prevista: `https://<usuario>.github.io/G-Patch-Notes/`

## Licencia

Por definir.
