"""
advanced_map_app.py

High-performance interactive Leaflet map widget for Panel that uses a shared
Canvas renderer for fast scatter plotting and flexible GeoJSON overlay
management. This module wires together Python-side state (Panel parameters)
with client-side JavaScript to provide a responsive, feature-rich mapping
experience suitable for exploratory data visualization.

Assets and client-side behavior
- js/render.js
    Initializes the Leaflet map, creates a shared Canvas renderer, and adds
    common UI controls (scale bar, fullscreen, zoom, measurement tool).
    Also wires mouse events used for hover behavior and drawing integration.
- js/sync_geojson.js
    Synchronizes GeoJSON overlay dictionaries provided by Python with Leaflet
    layers in the browser. Adds/removes layers, updates only when the JSON
    changes (stringified comparison), and keeps a layer control in-sync.
    Separates "hoverable" overlays (participate in nearest-point lookup) from
    static overlays.
- js/show_hover.js
    Toggles visibility of a reusable hover marker based on the Python
    `show_hover` flag. Actual placement of the hover marker is handled in
    the render.js mousemove handlers.
- js/after_layout.js
    Runs once after the Panel/Bokeh layout is finalized to call
    invalidateSize(), trigger overlay synchronization, and ensure the
    hover marker state matches Python-side settings.
- assets/template.html
    Minimal HTML template that defines the map container element used by the
    ReactiveHTML widget.
- assets/styles.css
    Custom CSS that overrides Leaflet UI fonts and tooltip appearance to
    provide a modern, rounded look.

Design goals and notes
- Fast client-side rendering for large point collections: scatter layers are
  sent as GeoJSON FeatureCollections and rendered with a shared L.canvas
  renderer. Coordinates are rounded to 6 decimal places to reduce payload
  size without noticeable loss of visual precision for typical zoom levels.
- Clear separation of hoverable vs non-hoverable overlays allows efficient
  nearest-point hover interaction without including all layers in the
  proximity index.
- The widget exposes a small, explicit Python API (add_layer, remove_layer,
  clear_layers, add_scatter) so users can programmatically control overlays
  from Python code. Drawn shapes are surfaced to Python via the
  `drawn_shapes` parameter.

Usage
- Import and instantiate AdvancedLeafletCanvas in a Panel app. Call
  add_scatter or add_layer to populate overlays. The module registers the
  custom CSS with pn.extension via raw_css to ensure consistent styling.

"""

import numpy as np
import panel as pn
import param
from panel.reactive import ReactiveHTML
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# --- Asset loading ---------------------------------------------------------
ROOT = Path(__file__).parent
JS_DIR = ROOT / "js"
ASSET_DIR = ROOT / "assets"


def _read(path: Path) -> str:
    """Read content from a file at the given path.

    Used internally to load JavaScript, HTML, and CSS assets that define the
    widget's client-side behavior and appearance.

    Args:
        path: Path object pointing to the file to read

    Returns:
        String content of the file
    """
    return path.read_text()


RENDER_JS = _read(JS_DIR / "render.js")        # Map initialization and controls
AFTER_LAYOUT_JS = _read(JS_DIR / "after_layout.js")  # Post-layout size fixes
SHOW_HOVER_JS = _read(JS_DIR / "show_hover.js")      # Hover marker toggle
SYNC_GEOJSON_JS = _read(JS_DIR / "sync_geojson.js")  # Overlay synchronization

TEMPLATE_HTML = _read(ASSET_DIR / "template.html")    # Map container template
CUSTOM_CSS = _read(ASSET_DIR / "styles.css")         # Modern UI styling


# --- AdvancedLeafletCanvas ------------------------------------------------
class AdvancedLeafletCanvas(ReactiveHTML):
    """Leaflet map with fast Canvas scatter, draw tools, measure, and fullscreen.

    This class implements a Panel ReactiveHTML widget that binds Python-side
    parameters to client-side Leaflet state using pre-bundled JavaScript and
    HTML assets. It is intended for exploratory visualizations where large
    scatter datasets (tens of thousands of points) and interactive GeoJSON
    overlays need to be displayed with good performance.

    Key responsibilities
    - Expose location/zoom (`center`, `zoom`) and global styling (`cmap`) as
      Panel parameters so they can be linked to other widgets.
    - Provide a simple overlay management API: `add_layer`, `remove_layer`,
      `clear_layers` for arbitrary GeoJSON, and `add_scatter` for
      convenience when creating large point collections from NumPy / lists.
    - Surface user-drawn shapes (from Leaflet.draw) via the `drawn_shapes`
      parameter so Python code can react to or persist shapes created in the
      browser.
    - Toggle hover interactivity using `show_hover`. Hover targets are
      restricted to layers placed in `geojson_hover_overlays` for efficiency.

    Important parameters (Panel params)
    - center (XYCoordinates): Default map center as (lat, lon).
    - zoom (Integer): Initial zoom level (bounds 1..22).
    - cmap (String): Default colormap name used by add_scatter when no
      per-layer cmap is supplied. If `values` are provided to add_scatter the
      collection-level properties include vmin/vmax and cmap for client-side
      coloring (client uses chroma-js).
    - show_hover (Boolean): Controls whether the reusable hover marker is
      visible and whether the client attaches mousemove handlers that find
      the nearest hoverable point.
    - map_options (Dict): Leaflet map options that override the widget's
      defaults (preferCanvas, zoomControl defaults are configurable).
    - tile_layers (Dict): Mapping of friendly name -> (tileURLTemplate, opts)
      used to populate base layers and the layer switcher. Each `opts`
      dictionary should contain any Leaflet tile layer options (e.g.,
      attribution).
    - drawn_shapes (List): Updated by client-side draw handlers. Each entry
      is the serialized GeoJSON for a drawn shape; users can watch this
      parameter to persist or react to new drawings.
    - geojson_overlays / geojson_hover_overlays (Dict): Two separate dicts
      holding non-hoverable and hoverable overlay GeoJSON respectively. The
      `sync_geojson.js` logic merges these on the client and keeps a
      Leaflet-control up-to-date.

    Methods
    - add_layer(name, geojson, hoverable=False): Add or replace a GeoJSON
      overlay. If hoverable=True the layer participates in nearest-point
      hover lookups.
    - remove_layer(name): Remove a named overlay from either group.
    - clear_layers(): Remove all overlays.
    - add_scatter(name, lats, lons, values=None, cmap=None, radius=3,
      fill_opacity=0.8, hoverable=False): Convenience to build a
      FeatureCollection from coordinate arrays. When `values` is provided the
      features include a `properties.value` and the collection contains
      vmin/vmax/cmap to enable client-side continuous coloring.

    Client-side integration details
    - _template: uses assets/template.html which contains a container with a
      #map element. ReactiveHTML injects this HTML into the document.
    - _scripts: binds the JavaScript sources (render.js, sync_geojson.js,
      show_hover.js, after_layout.js) to the widget lifecycle. The
      `sync_geojson` script is triggered whenever the two overlay params
      change, ensuring near real-time updates.
    - __css__: includes Leaflet and plugin CSS. Additionally, the module
      registers a small custom stylesheet (assets/styles.css) via
      pn.extension(raw_css=...) to tweak font and tooltip appearance.
    - __javascript__: includes chroma-js (for colormaps), Leaflet 1.7.1 and
      a few plugins (draw, measure, fullscreen). Note: Leaflet 1.7.1 is
      intentionally chosen because later versions may break the measure
      plugin's behavior.

    Performance and payload considerations
    - Coordinates are rounded to 6 decimals in add_scatter to reduce JSON
      payload size. The shared Canvas renderer provides very good
      performance for large point counts, but application responsiveness
      also depends on network and browser capabilities.

    Example
    >>> leaf = AdvancedLeafletCanvas(cmap='Inferno', show_hover=True)
    >>> leaf.add_scatter('points', lats, lons, values=v)
    >>> pn.Row(leaf, pn.pane.JSON(leaf.param.drawn_shapes)).servable()
    """

    # Map state / configuration (Panel parameters)
    center = param.XYCoordinates(default=(37.0, -122.0))
    zoom = param.Integer(default=9, bounds=(1, 22))
    cmap = param.String(default="Viridis")
    show_hover = param.Boolean(default=False)
    map_options = param.Dict(default={})

    container_style = param.String(default="width:100%;height:100%;")

    # Tile layers: mapping name -> (urlTemplate, options)
    tile_layers = param.Dict(
        default={
            "OSM": (
                "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                {"attribution": "&copy; OSM contributors"},
            ),
            "Topo": (
                "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
                {"attribution": "&copy; OpenTopoMap contributors"},
            ),
        }
    )

    drawn_shapes = param.List(default=[])

    # Two overlay groups: hoverable and non-hoverable
    geojson_overlays = param.Dict(default={})
    geojson_hover_overlays = param.Dict(default={})

    # --- Layer management API ----------------------------------------------
    def add_layer(self, name: str, geojson: Dict[str, Any], hoverable: bool = False) -> None:
        """Add or replace a GeoJSON overlay layer in the appropriate group.

        Manages two separate overlay dictionaries (hoverable and non-hoverable) to
        support efficient client-side hover behavior. When hoverable=True, the
        layer's points will participate in nearest-point hover calculations.
        The sync_geojson.js client code merges these dictionaries and keeps a
        Leaflet layer control up-to-date.

        Args:
            name: Unique identifier for the layer. If a layer with this name
                exists in either group, it will be replaced.
            geojson: Valid GeoJSON data. For scatter layers this is typically a
                FeatureCollection with Point features and collection-level
                styling properties.
            hoverable: If True, layer points will be included in hover proximity
                checks and the nearest point will be highlighted when the mouse
                is nearby.

        Notes:
            - Layer switching between hoverable/non-hoverable groups is handled
              by removing from the old group when adding to the new one.
            - Client-side changes are triggered by param.geojson_*_overlays
              watchers that invoke sync_geojson().
        """
        if hoverable:
            new: Dict[str, Any] = dict(self.geojson_hover_overlays)
            new[name] = geojson
            self.geojson_hover_overlays = new
            # Ensure it's not also in the non-hover group
            if name in self.geojson_overlays:
                other: Dict[str, Any] = dict(self.geojson_overlays)
                other.pop(name, None)
                self.geojson_overlays = other
        else:
            new: Dict[str, Any] = dict(self.geojson_overlays)
            new[name] = geojson
            self.geojson_overlays = new
            if name in self.geojson_hover_overlays:
                other: Dict[str, Any] = dict(self.geojson_hover_overlays)
                other.pop(name, None)
                self.geojson_hover_overlays = other

    def remove_layer(self, name: str) -> None:
        """Remove a named layer from either overlay group if present.

        Checks both hoverable and non-hoverable dictionaries for the named layer
        and removes it if found. The sync_geojson.js client code will detect
        the removal and update the Leaflet map accordingly.

        Args:
            name: Name of the layer to remove. If not found in either group,
                this is a no-op.

        Notes:
            - Changes to either overlay dictionary trigger client-side updates
              via the sync_geojson() JavaScript handler.
            - The client maintains a mapping of layer name -> Leaflet layer and
              removes layers no longer present in either Python dictionary.
        """
        if name in self.geojson_overlays:
            d: Dict[str, Any] = dict(self.geojson_overlays)
            d.pop(name, None)
            self.geojson_overlays = d
        if name in self.geojson_hover_overlays:
            d: Dict[str, Any] = dict(self.geojson_hover_overlays)
            d.pop(name, None)
            self.geojson_hover_overlays = d

    def clear_layers(self) -> None:
        """Remove all overlay layers from both hoverable and non-hoverable groups.

        This is a convenience method that empties both overlay dictionaries,
        triggering a full client-side synchronization that will remove all
        layers from the map and layer control.

        Notes:
            - Client-side sync happens automatically via param watchers that
              call sync_geojson() when either dictionary changes.
            - The sync logic efficiently handles bulk removals by comparing
              the set of desired layers against what's currently on the map.
        """
        self.geojson_overlays = {}
        self.geojson_hover_overlays = {}

    # --- Convenience: add large scatter as GeoJSON FeatureCollection --------
    def add_scatter(
            self,
            name: str,
            lats: Iterable[float],
            lons: Iterable[float],
            values: Optional[Iterable[float]] = None,
            cmap: Optional[str] = None,
            radius: int = 3,
            fill_opacity: float = 0.8,
            hoverable: bool = False,
    ) -> None:
        """Add/update a scatter overlay as a GeoJSON FeatureCollection.

        This is a high-level convenience method that builds a GeoJSON Feature
        Collection from coordinate arrays, with optional per-point values for
        continuous coloring. The collection includes styling properties that
        control point appearance and coloring behavior.

        Args:
            name: Unique identifier for the scatter layer
            lats: Latitude coordinates for points
            lons: Longitude coordinates for points
            values: Optional values for continuous coloring. When provided,
                features get properties.value and collection-level vmin/vmax/cmap
                enable client-side coloring using chroma-js.
            cmap: Color or colormap name. For valued points this is a chroma-js
                colormap (e.g., 'Viridis'). Without values it's a plain color
                name (e.g., 'blue').
            radius: Point radius in pixels
            fill_opacity: Point fill opacity (0-1)
            hoverable: Whether points participate in hover interactions

        Notes:
            - Coordinates are rounded to 6 decimal places to reduce payload size
              while maintaining visual precision at typical zoom levels.
            - Collection-level properties (radius, fillOpacity, vmin/vmax/cmap)
              are used by render.js to style points efficiently.
            - Values/colormap settings integrate with chroma-js on the client
              for smooth continuous coloring.
            - The shared Canvas renderer (L.canvas) provides good performance
              for large point counts.

        JavaScript Integration:
            - render.js: Configures Canvas renderer and hover behavior
            - sync_geojson.js: Ensures layer appears on map with correct styling
            - show_hover.js: Controls point hover highlighting if hoverable=True
        """
        # Normalize coordinates and reduce precision to keep payload small
        lats = [round(float(x), 6) for x in lats]
        lons = [round(float(x), 6) for x in lons]

        if values is not None:
            vals = [float(v) for v in values]
            n = min(len(lats), len(lons), len(vals))
            vmin = min(vals[:n]) if n else 0.0
            vmax = max(vals[:n]) if n else 1.0
        else:
            vals = None
            n = min(len(lats), len(lons))
            vmin = vmax = None

        cmap_val = cmap if cmap is not None else self.cmap

        collection_props: Dict[str, Any] = {
            "radius": int(radius),
            "fillOpacity": float(fill_opacity),
        }
        if vals is not None:
            collection_props.update({"vmin": vmin, "vmax": vmax, "cmap": cmap_val})
        else:
            collection_props.update({"color": cmap_val})

        features: List[Dict[str, Any]] = []
        for i in range(n):
            feat: Dict[str, Any] = {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lons[i], lats[i]]},
                "properties": {},
            }
            if vals is not None:
                feat["properties"]["value"] = vals[i]
            features.append(feat)

        geojson = {"type": "FeatureCollection", "features": features, "properties": collection_props}
        self.add_layer(name, geojson, hoverable=hoverable)

    # --- ReactiveHTML configuration ---------------------------------------
    _template = TEMPLATE_HTML

    _scripts = {
        "render": RENDER_JS,
        "after_layout": AFTER_LAYOUT_JS,
        "show_hover": SHOW_HOVER_JS,
        "sync_geojson": SYNC_GEOJSON_JS,
        # Trigger sync whenever either param changes
        "geojson_overlays": "self.sync_geojson()",
        "geojson_hover_overlays": "self.sync_geojson()",
    }

    _extension_name = "leaflet"

    __css__ = [
        "https://unpkg.com/leaflet@1.7.1/dist/leaflet.css",
        "https://unpkg.com/leaflet-draw/dist/leaflet.draw.css",
        "https://unpkg.com/leaflet-measure/dist/leaflet-measure.css",
        "https://api.mapbox.com/mapbox.js/plugins/leaflet-fullscreen/v1.0.1/leaflet.fullscreen.css",
    ]

    __javascript__ = [
        "https://unpkg.com/chroma-js@2.4.2/chroma.min.js",
        # leaflet 1.7.1 is the last version to support Measure control properly
        "https://unpkg.com/leaflet@1.7.1/dist/leaflet.js",
        "https://unpkg.com/leaflet-draw/dist/leaflet.draw.js",
        "https://unpkg.com/leaflet-measure/dist/leaflet-measure.js",
        "https://api.mapbox.com/mapbox.js/plugins/leaflet-fullscreen/v1.0.1/Leaflet.fullscreen.min.js",
    ]


# --- Module-level setup and example app ------------------------------------
pn.extension("leaflet", raw_css=[CUSTOM_CSS])


def create_example_app(n: int = 20000) -> pn.Row:
    """Create an example application with three scatter layers and a JSON pane.

    Demonstrates key features of AdvancedLeafletCanvas:
    - Large scatter layers with continuous coloring (values + colormap)
    - Simple colored scatter without values
    - Hoverable vs non-hoverable layers
    - Integration with Panel's pn.bind for tracking drawn shapes

    Args:
        n: Number of points to generate in each scatter layer

    Returns:
        Panel Row containing the map and a JSON pane showing drawn shapes.
        The shapes pane updates automatically when users draw on the map.

    Notes:
        - Uses sinusoidal patterns to create visually distinct layers
        - Layer 1: Continuous coloring with hoverable points
        - Layer 2: Single color (blue) with hover
        - Layer 3: Random values, no hover, demonstrates separation
    """
    t = np.linspace(0, 2 * np.pi, n)
    lat = 37.3 + 0.1 * np.sin(t)
    lon = -122.0 + 0.1 * np.cos(t)

    leaf = AdvancedLeafletCanvas(
        cmap="Inferno",
        container_style="width:600px;height:500px;border:1px solid gray;",
        show_hover=True,
    )

    # Layer 1: colored by value (hoverable)
    leaf.add_scatter(
        name="Example Scatter",
        lats=lat,
        lons=lon,
        values=np.linspace(-1, 1, n),
        cmap="Viridis",
        radius=3,
        fill_opacity=0.8,
        hoverable=True,
    )

    # Layer 2: simple color, offset
    leaf.add_scatter(
        name="Example Scatter 2",
        lats=lat + 0.1,
        lons=lon + 0.1,
        cmap="blue",
        radius=3,
        fill_opacity=0.8,
        hoverable=True,
    )

    # Layer 3: non-hoverable, random values
    leaf.add_scatter(
        name="Example Scatter 3 - no hover",
        lats=lat + 0.2,
        lons=lon + 0.2,
        values=np.random.rand(n) * 100,
        cmap="Inferno",
        radius=3,
        fill_opacity=0.8,
        hoverable=False,
    )

    shapes_pane = pn.pane.JSON(pn.bind(lambda s: s, leaf.param.drawn_shapes), depth=3)
    return pn.Row(leaf, shapes_pane)


""" Run using 'panel serve ./advanced_map_app.py --dev' """
app = create_example_app()
app.servable()
