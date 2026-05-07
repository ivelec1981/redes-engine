# Contribuir a redes_engine

¡Gracias por tu interés en contribuir! Este documento explica cómo aportar
al proyecto de manera efectiva.

## 🚀 Setup de desarrollo

```bash
# 1. Clonar el repo
git clone https://github.com/ivelec1981/redes-engine.git
cd redes-engine

# 2. Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate              # Windows

# 3. Instalar en modo editable con todas las extras
pip install -e ".[all,dev]"

# 4. Validar que todo funciona
pytest tests/ -v
```

## 📋 Antes de hacer un PR

1. **Tests pasan**: `pytest tests/`
2. **Lint limpio**: `ruff check redes_engine/`
3. **Sin warnings nuevos**: revisa los logs
4. **Cobertura ≥ 80%** para código nuevo

## 🎯 Tipos de contribuciones bienvenidas

### 🐛 Bug fixes
1. Abre un Issue describiendo el bug (paso a paso para reproducirlo)
2. Crea una rama: `git checkout -b fix/descripcion-corta`
3. Añade un test que falla por el bug
4. Corrige el bug; el test debe pasar
5. PR con referencia al issue

### ✨ Features nuevos
1. **Discute primero** en un Issue — evita trabajo desperdiciado
2. Diseño breve: qué API expones, qué tests añades
3. Implementa y testea
4. Documenta en docstrings y README si aplica

### 📚 Documentación
- Todas las contribuciones de docs son bienvenidas (README, ejemplos, traducciones)
- Mantén el tono del proyecto: directo, técnico, sin marketing

### 🌎 Localización (otros países)
El motor está alineado con normativa Ecuador (ARCERNNR), pero está
diseñado para extender a Colombia, Perú, México, etc. Si tu empresa
quiere añadir su normativa:

1. Crea un módulo `redes_engine/core/normativas/<pais>.py`
2. Define `NormativeLimits` con los valores de tu regulador
3. Añade tests con casos específicos
4. Documenta diferencias en README

## 📐 Estilo de código

Seguimos PEP 8 con `ruff` como linter:
- 100 caracteres por línea (soft limit)
- 4 espacios de indentación
- Type hints en funciones públicas
- Docstrings en formato NumPy:

```python
def my_function(param: int, other: str = "default") -> bool:
    """
    Breve descripción de qué hace.

    Parameters
    ----------
    param : int
        Descripción del parámetro.
    other : str, optional
        Descripción opcional.

    Returns
    -------
    bool
        Qué retorna.

    Examples
    --------
    >>> my_function(42)
    True
    """
    ...
```

## 🧪 Tests

Usamos `pytest`. Estructura:
```
tests/
├── test_graph.py            # tests del modelo de datos
├── test_solver.py           # tests del bridge OpenDSS
├── test_hosting.py          # tests de host capacity
└── ...
```

Para tests que requieren OpenDSS:
```python
opendss = pytest.importorskip("opendssdirect", reason="opendssdirect no instalado")
```

## 🔄 Workflow de PR

```
fork → clone → branch → commit → push → PR
```

Branch naming:
- `fix/<short-description>` — bug fixes
- `feat/<short-description>` — features
- `docs/<short-description>` — solo documentación
- `refactor/<short-description>` — refactor sin cambio de comportamiento
- `test/<short-description>` — solo tests

Commit messages (estilo Conventional Commits):
```
feat: agregar soporte para CREG Colombia
fix: corregir cálculo de pérdidas en trafo
docs: actualizar README con sección de Docker
test: cubrir casos edge de bisección hosting
refactor: extraer dispatcher BESS a módulo independiente
```

## 🤝 Code of Conduct

Sé profesional, paciente y constructivo. Las discusiones técnicas
son bienvenidas; los ataques personales no.

## 📬 Comunicación

- **Issues**: bugs y features
- **Discussions**: preguntas técnicas, casos de uso, design RFCs
- **PRs**: código

---

¡Gracias por hacer del software eléctrico open-source una realidad! ⚡
