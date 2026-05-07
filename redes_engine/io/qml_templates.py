# -*- coding: utf-8 -*-
"""
redes_engine.io.qml_templates
==============================

Generadores de archivos QML (estilo QGIS) sin dependencia de QGIS.

QML es XML estándar — podemos generarlo manualmente y QGIS lo aplicará
automáticamente cuando cargue las capas correspondientes (mismo nombre
base que el archivo de la capa).

Esquemas implementados:
    - bus_compliance     : círculos coloreados por estado normativo
    - line_loading       : líneas graduadas por % de carga (verde→rojo)
    - transformer_loading: símbolos categóricos por % de carga
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom

# =============================================================================
# Colores estándar (semáforo eléctrico)
# =============================================================================
COLOR_OK         = "46,204,113,255"      # verde — cumple
COLOR_WARNING    = "243,156,18,255"      # naranja — advertencia
COLOR_VIOLATION  = "231,76,60,255"       # rojo — violación
COLOR_UNKNOWN    = "189,195,199,255"     # gris — desconocido

COLOR_LOAD_LOW       = "46,204,113,255"      # 0-50%
COLOR_LOAD_MED       = "241,196,15,255"      # 50-80%
COLOR_LOAD_HIGH      = "230,126,34,255"      # 80-100%
COLOR_LOAD_OVERLOAD  = "192,57,43,255"       # >100%


# =============================================================================
# Generador para BUSES (estilo categórico por compliance)
# =============================================================================
def qml_buses_compliance() -> str:
    """
    Genera QML para puntos (buses) categorizados por estado de cumplimiento.
    Atributo de control: 'compliance' (string: ok/warning/violation/unknown).
    """
    qml = '''<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling">
  <renderer-v2 forceraster="0" type="categorizedSymbol" attr="compliance" symbollevels="0" enableorderby="0">
    <categories>
      <category value="ok" symbol="0" label="✅ Cumple normativa" render="true"/>
      <category value="warning" symbol="1" label="🟡 Advertencia" render="true"/>
      <category value="violation" symbol="2" label="❌ Violación" render="true"/>
      <category value="unknown" symbol="3" label="⚪ Sin evaluar" render="true"/>
    </categories>
    <symbols>
      ''' + _marker_symbol("0", COLOR_OK, size=3.5) + '''
      ''' + _marker_symbol("1", COLOR_WARNING, size=4.0) + '''
      ''' + _marker_symbol("2", COLOR_VIOLATION, size=5.0) + '''
      ''' + _marker_symbol("3", COLOR_UNKNOWN, size=2.5) + '''
    </symbols>
    <source-symbol>
      ''' + _marker_symbol("source", COLOR_UNKNOWN, size=2.5) + '''
    </source-symbol>
  </renderer-v2>
  <labeling type="simple">
    <settings>
      <text-style fontFamily="Segoe UI" fontSize="8" textColor="44,62,80,255" fontWeight="50">
        <text-buffer bufferDraw="1" bufferSize="1" bufferColor="255,255,255,200"/>
      </text-style>
      <placement placement="2" dist="2"/>
      <rendering scaleVisibility="0"/>
      <text-format>
        <expression>concat("ID: ", "id", '\\n', "V%: ", round("v_drop_pct", 2), '%')</expression>
      </text-format>
    </settings>
  </labeling>
</qgis>'''
    return qml


# =============================================================================
# Generador para LÍNEAS (estilo graduado por loading_pct)
# =============================================================================
def qml_lines_loading() -> str:
    """
    Genera QML para líneas graduadas por % de carga.
    Atributo de control: 'loading_pct' (numeric).
    """
    qml = '''<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling">
  <renderer-v2 forceraster="0" type="graduatedSymbol" attr="loading_pct" graduatedMethod="GraduatedColor" symbollevels="0">
    <ranges>
      <range lower="0.0" upper="50.0" symbol="0" label="0-50% (subutilizada)" render="true"/>
      <range lower="50.0" upper="80.0" symbol="1" label="50-80% (operación normal)" render="true"/>
      <range lower="80.0" upper="100.0" symbol="2" label="80-100% (advertencia)" render="true"/>
      <range lower="100.0" upper="999.0" symbol="3" label=">100% (sobrecarga)" render="true"/>
    </ranges>
    <symbols>
      ''' + _line_symbol("0", COLOR_LOAD_LOW, width=0.6) + '''
      ''' + _line_symbol("1", COLOR_LOAD_MED, width=0.9) + '''
      ''' + _line_symbol("2", COLOR_LOAD_HIGH, width=1.4) + '''
      ''' + _line_symbol("3", COLOR_LOAD_OVERLOAD, width=2.0) + '''
    </symbols>
    <source-symbol>
      ''' + _line_symbol("source", COLOR_LOAD_LOW, width=0.5) + '''
    </source-symbol>
    <classificationMethod id="EqualInterval">
      <symmetricMode enabled="0" symmetrypoint="0" astride="0"/>
    </classificationMethod>
  </renderer-v2>
  <labeling type="simple">
    <settings>
      <text-style fontFamily="Segoe UI" fontSize="7" textColor="44,62,80,255">
        <text-buffer bufferDraw="1" bufferSize="0.8" bufferColor="255,255,255,200"/>
      </text-style>
      <placement placement="3" dist="1.5"/>
      <text-format>
        <expression>concat("id", '\\n', round("loading_pct", 1), '%')</expression>
      </text-format>
    </settings>
  </labeling>
</qgis>'''
    return qml


# =============================================================================
# Generador para TRANSFORMADORES
# =============================================================================
def qml_transformers_loading() -> str:
    """
    Genera QML para transformadores categorizados por compliance + loading.
    """
    qml = '''<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling">
  <renderer-v2 forceraster="0" type="categorizedSymbol" attr="compliance" symbollevels="0">
    <categories>
      <category value="ok" symbol="0" label="✅ Trafo cumple" render="true"/>
      <category value="warning" symbol="1" label="🟡 Trafo cerca del límite" render="true"/>
      <category value="violation" symbol="2" label="❌ Trafo SOBRECARGADO" render="true"/>
    </categories>
    <symbols>
      ''' + _marker_symbol("0", COLOR_OK, size=6.0, shape="square") + '''
      ''' + _marker_symbol("1", COLOR_WARNING, size=7.0, shape="square") + '''
      ''' + _marker_symbol("2", COLOR_VIOLATION, size=8.0, shape="square") + '''
    </symbols>
    <source-symbol>
      ''' + _marker_symbol("source", COLOR_UNKNOWN, size=5.0, shape="square") + '''
    </source-symbol>
  </renderer-v2>
  <labeling type="simple">
    <settings>
      <text-style fontFamily="Segoe UI" fontSize="9" textColor="44,62,80,255" fontWeight="75">
        <text-buffer bufferDraw="1" bufferSize="1.2" bufferColor="255,255,255,220"/>
      </text-style>
      <placement placement="0" yOffset="-3" dist="0"/>
      <text-format>
        <expression>concat("id", '\\n', "kva", ' kVA - ', round("loading_pct", 1), '%')</expression>
      </text-format>
    </settings>
  </labeling>
</qgis>'''
    return qml


# =============================================================================
# Helpers — bloques XML reutilizables
# =============================================================================
def _marker_symbol(name: str, color: str, size: float = 3.0,
                   shape: str = "circle") -> str:
    """Genera un bloque <symbol> de tipo marker."""
    return f'''<symbol type="marker" name="{name}" alpha="1" force_rhr="0" clip_to_extent="1">
        <layer locked="0" enabled="1" pass="0" class="SimpleMarker">
          <Option type="Map">
            <Option name="color" type="QString" value="{color}"/>
            <Option name="name" type="QString" value="{shape}"/>
            <Option name="outline_color" type="QString" value="44,62,80,255"/>
            <Option name="outline_style" type="QString" value="solid"/>
            <Option name="outline_width" type="QString" value="0.4"/>
            <Option name="outline_width_unit" type="QString" value="MM"/>
            <Option name="size" type="QString" value="{size}"/>
            <Option name="size_unit" type="QString" value="MM"/>
            <Option name="vertical_anchor_point" type="QString" value="1"/>
          </Option>
        </layer>
      </symbol>'''


def _line_symbol(name: str, color: str, width: float = 0.6) -> str:
    """Genera un bloque <symbol> de tipo línea."""
    return f'''<symbol type="line" name="{name}" alpha="1" force_rhr="0" clip_to_extent="1">
        <layer locked="0" enabled="1" pass="0" class="SimpleLine">
          <Option type="Map">
            <Option name="line_color" type="QString" value="{color}"/>
            <Option name="line_style" type="QString" value="solid"/>
            <Option name="line_width" type="QString" value="{width}"/>
            <Option name="line_width_unit" type="QString" value="MM"/>
            <Option name="capstyle" type="QString" value="round"/>
            <Option name="joinstyle" type="QString" value="round"/>
          </Option>
        </layer>
      </symbol>'''


# =============================================================================
# Validación
# =============================================================================
def validate_qml(qml_string: str) -> bool:
    """Verifica que el QML generado sea XML válido."""
    try:
        ET.fromstring(qml_string)
        return True
    except ET.ParseError:
        return False
