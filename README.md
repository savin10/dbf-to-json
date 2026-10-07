# DBF → JSON

Plateforme web pour convertir des fichiers DBF (dBase III/IV, FoxPro, Visual FoxPro) en JSON.
Backend **FastAPI**, frontend **HTML / CSS / JavaScript** sans framework.

## Démarrage

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

Puis ouvrir http://127.0.0.1:8000

## Fonctionnalités

- Glisser-déposer de plusieurs fichiers ; les fichiers mémo `.dbt` / `.fpt` sont associés automatiquement au `.dbf` du même nom
- Aperçu : tableau des données, schéma des champs, rendu JSON
- Encodage détecté automatiquement depuis l'en-tête (ou choisi manuellement)
- Options : schéma inclus ou non, JSON indenté, noms en minuscules, enregistrements supprimés (`_deleted`)
- Conversion en streaming : les gros fichiers ne sont pas chargés entièrement en mémoire (limite d'upload : 500 Mo)

## API

| Méthode | Route          | Description                                        |
|---------|----------------|----------------------------------------------------|
| POST    | `/api/inspect` | Métadonnées + premiers enregistrements (aperçu)    |
| POST    | `/api/convert` | Télécharge le fichier JSON complet                 |
| GET     | `/api/health`  | Vérification de l'état                             |

Champs du formulaire (multipart) : `dbf` (requis), `memo`, `encoding`, `include_deleted`,
`lowercase`, `include_schema`, `pretty`.

```bash
curl -F dbf=@clients.dbf -F memo=@clients.dbt localhost:8000/api/convert -o clients.json
```

Conversion des types : dates → ISO 8601, numériques → nombres JSON, logiques → `true`/`false`/`null`,
binaires (G, P, Q…) → `{"$binary": "<base64>"}`.

## Tests

```bash
.venv/bin/python -m pytest
```
