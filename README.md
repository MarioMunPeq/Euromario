# EuroMario

Agregador de noticias de videojuegos que rastrea, filtra y resume automáticamente contenido de medios especializados, Steam y Reddit — publicado como página estática y actualizado cada hora, sin coste de infraestructura.

🔗 **Demo en vivo:** https://mariomunpeq.github.io/Euromario/

---

## Qué hace

- Rastrea noticias de medios (IGN, Eurogamer, PC Gamer, Polygon, Rock Paper Shotgun), la API oficial de Steam News, y subreddits de la comunidad (marcados como contenido no verificado).
- Filtra el contenido por una lista de juegos/sagas seguidos, con exclusión de juegos no deseados.
- Resume y clasifica cada noticia con IA (modelo local vía Ollama, con fallback automático a Groq si el modelo local no está disponible).
- Publica el resultado en una web estática, sin backend ni base de datos — todo vive en un archivo JSON generado por el propio pipeline.
- Se ejecuta automáticamente cada hora mediante GitHub Actions.

## Por qué existe

Proyecto de portfolio para practicar un pipeline completo de extremo a extremo: scraping, procesamiento con IA, automatización CI/CD, y frontend — todo con coste cero, usando únicamente herramientas y niveles gratuitos.

## Stack técnico

| Componente | Tecnología |
|---|---|
| Lenguaje principal | Python 3.12+ |
| Scraping / RSS | `feedparser`, `requests`, `BeautifulSoup` |
| IA / resumen | Ollama (modelo local) con fallback a Groq (API gratuita) |
| Tests | `pytest`, `ruff` |
| Automatización | GitHub Actions (cron horario) |
| Almacenamiento | JSON plano versionado en el propio repo |
| Frontend | HTML / CSS / JavaScript vanilla (sin frameworks) |
| Hosting | GitHub Pages |

## Cómo funciona el pipeline

1. **Fetch** — descarga noticias de RSS de medios, la API de Steam News, y RSS de subreddits configurados.
2. **Filtrado** — aplica una lista de inclusión (juegos seguidos) y exclusión (juegos vetados), con lógica de "tema principal" para evitar ruido.
3. **Resumen con IA** — cada noticia se resume, clasifica (lanzamiento / actualización / rumor / análisis) y puntúa por relevancia.
4. **Persistencia** — el resultado se fusiona con el histórico existente, se aplica una política de retención (14 días o 200 items, lo que ocurra primero), y se escribe de forma atómica.
5. **Publicación** — el frontend estático lee ese JSON y lo muestra con filtros por juego, categoría y fecha.

## Ejecutar en local

```bash
git clone https://github.com/MarioMunPeq/Euromario.git
cd Euromario
pip install -r requirements.txt --break-system-packages

# Configurar la clave de Groq (o tener Ollama corriendo en local)
echo "GROQ_API_KEY=tu-clave-aqui" > .env

python -m gaming_news_digest
```

Para ver el frontend con los datos generados:

```bash
cd frontend
python -m http.server 8000
# abrir http://localhost:8000
```

## Configuración

- `config/games.yaml` — lista de juegos/sagas a seguir (inclusión) y a excluir.
- `config/sources.yaml` — feeds RSS de medios, IDs de juegos en Steam, y subreddits a rastrear.

## Documentación técnica

Ver [`CONTRIBUTING.md`](./CONTRIBUTING.md) para el detalle completo de arquitectura, contrato del JSON, política de reintentos de IA, y convenciones de código.

## Estado del proyecto

En desarrollo activo — el pipeline de backend está funcionando en producción; el frontend está en fase de rediseño visual.
