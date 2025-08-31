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
    return path.read_text()


RENDER_JS = _read(JS_DIR / "render.js")
AFTER_LAYOUT_JS = _read(JS_DIR / "after_layout.js")
SHOW_HOVER_JS = _read(JS_DIR / "show_hover.js")
SYNC_GEOJSON_JS = _read(JS_DIR / "sync_geojson.js")

TEMPLATE_HTML = _read(ASSET_DIR / "template.html")
CUSTOM_CSS = _read(ASSET_DIR / "styles.css")


# --- AdvancedLeafletCanvas ------------------------------------------------
class AdvancedLeafletCanvas(ReactiveHTML):
    """Leaflet map with fast Canvas scatter, draw tools, measure, and fullscreen.

    Provides a simple Python API to manage GeoJSON overlay layers and to add
    large scatter layers which are pushed to the client as GeoJSON.
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
        """Add or replace a GeoJSON overlay layer.

        If hoverable=True the layer will be placed in the hoverable group so
        the client includes its point features in nearest-point hover logic.
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
        """Remove a named layer from either overlay group if present."""
        if name in self.geojson_overlays:
            d: Dict[str, Any] = dict(self.geojson_overlays)
            d.pop(name, None)
            self.geojson_overlays = d
        if name in self.geojson_hover_overlays:
            d: Dict[str, Any] = dict(self.geojson_hover_overlays)
            d.pop(name, None)
            self.geojson_hover_overlays = d

    def clear_layers(self) -> None:
        """Remove all overlay layers from both groups."""
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

        Per-collection styling (radius, fillOpacity) is kept in collection
        properties to reduce payload. If `values` is provided each feature
        receives a properties.value and vmin/vmax/cmap are written at the
        collection level for client-side coloring.
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

    Demonstrates one value-colored layer, one plain color layer and one
    non-hoverable random layer.
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


app = create_example_app()
app.servable()
