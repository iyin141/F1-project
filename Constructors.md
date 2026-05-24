# Constructors — Code Map

Files under `backend/api/constructors` and related items used to build constructor standings and constructor-specific endpoints.

Files:

- `api/constructors/__init__.py`
- `api/constructors/views.py`
- `api/constructors/urls.py`
- `api/constructors/serializers.py`
- `api/constructors/repository.py`
- `api/constructors/services.py`
- `api/constructors/jolpica_client.py`

Diagram:

```mermaid
flowchart LR
  subgraph Constructors
    V[api/constructors/views.py]
    SRV[api/constructors/services.py]
    REPO[api/constructors/repository.py]
    MODEL[api/models/standings.py]
    JOL[api/constructors/jolpica_client.py]
    MGMT[api/management/commands/populate_constructor_standings.py]
  end

  V --> SRV
  SRV --> REPO
  REPO --> MODEL
  SRV --> JOL
  MGMT --> SRV
```

Notes:

- Constructor standings are populated by management commands and background tasks; repository functions centralize DB access.
