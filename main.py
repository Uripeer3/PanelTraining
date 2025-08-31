import panel as pn
import param
from panel.reactive import ReactiveHTML
from pathlib import Path


JS_DIR = Path(__file__).parent / "js"
RENDER_JS = (JS_DIR / "render.js").read_text()
AFTER_LAYOUT_JS = (JS_DIR / "after_layout.js").read_text()
SHOW_HOVER_JS = (JS_DIR / "show_hover.js").read_text()
SYNC_GEOJSON_JS = (JS_DIR / "sync_geojson.js").read_text()


class LeafletCanvasScatter(ReactiveHTML):
    """Leaflet map with chroma.js colormap + Canvas-Scatter for high-performance scatter, with draw + measure + fullscreen."""

    # Data/state
    center = param.XYCoordinates(default=(37.0, -122.0))
    zoom = param.Integer(default=9, bounds=(1, 22))
    cmap = param.String(default="Viridis")
    show_hover = param.Boolean(default=False)
    map_options = param.Dict(
        default={}
    )  # Optional Leaflet L.map options (camelCase), merged with defaults in JS

    container_style = param.String(default="width:100%;height:100%;")
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

    # Separate GeoJSON overlay groups:
    # - geojson_overlays: non-hoverable overlays
    # - geojson_hover_overlays: overlays whose point features participate in nearest-point hover
    geojson_overlays = param.Dict(default={})
    geojson_hover_overlays = param.Dict(default={})

    # Server-side API (Python) to manage GeoJSON overlay layers
    def add_layer(self, name: str, geojson: dict, hoverable: bool = False) -> None:
        """Add or update a GeoJSON overlay layer by name.

        If hoverable=True the client will include its point features in the nearest-point hover logic.
        """
        if name in self.geojson_overlays or name in self.geojson_hover_overlays:
            self.remove_layer(name)
        if hoverable:
            layers = dict(self.geojson_hover_overlays)
            layers[name] = geojson
            self.geojson_hover_overlays = layers
        else:
            layers = dict(self.geojson_overlays)
            layers[name] = geojson
            self.geojson_overlays = layers

    def remove_layer(self, name: str) -> None:
        """Remove a GeoJSON overlay layer by name, if it exists (in either group)."""
        if name in self.geojson_overlays:
            layers = dict(self.geojson_overlays)
            del layers[name]
            self.geojson_overlays = layers
        if name in self.geojson_hover_overlays:
            hlayers = dict(self.geojson_hover_overlays)
            del hlayers[name]
            self.geojson_hover_overlays = hlayers

    def clear_layers(self) -> None:
        """Remove all GeoJSON overlay layers from both groups."""
        self.geojson_overlays = {}
        self.geojson_hover_overlays = {}

    # Server-side helpers to add scatter overlays by generating GeoJSON Points
    def add_scatter(
        self,
        name: str,
        lats,
        lons,
        values=None,
        cmap=None,
        radius: int = 3,
        fill_opacity: float = 0.8,
        hoverable=False,
    ) -> None:
        """Add/update a colored scatter overlay as GeoJSON Points rendered client-side.
        Each point is a Feature with properties controlling styling:
        - If values is provided: properties.value, collection-level properties.vmin/vmax/cmap (not repeated per feature)
        - Otherwise: collection-level properties.color
        - properties.radius, properties.fill_opacity set at collection-level to avoid repetition
        """
        lats = list(map(float, lats))
        lons = list(map(float, lons))
        # Round to reduce payload size without visible impact on web map rendering
        lats = [round(x, 6) for x in lats]
        lons = [round(x, 6) for x in lons]

        if values is not None:
            values = list(map(float, values))
            n = min(len(lats), len(lons), len(values))
            vmin = min(values[:n]) if n else 0.0
            vmax = max(values[:n]) if n else 1.0
        else:
            n = min(len(lats), len(lons))
            vmin = vmax = None
        cmap_val = cmap if cmap is not None else self.cmap

        # Put shared properties at the collection level to avoid repeating them per feature
        collection_props = {
            "radius": int(radius),
            "fillOpacity": float(fill_opacity),  # Leaflet option key casing
        }
        if values is not None:
            collection_props.update({"vmin": vmin, "vmax": vmax, "cmap": cmap_val})
        else:
            collection_props.update({"color": cmap_val})

        features = []
        if values is not None:
            for i in range(n):
                # Only value is per-point; other styling lives at collection level
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [lons[i], lats[i]],
                        },
                        "properties": {"value": values[i]},
                    }
                )
        else:
            for i in range(n):
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [lons[i], lats[i]],
                        },
                        "properties": {},
                    }
                )

        geojson = {
            "type": "FeatureCollection",
            "features": features,
            "properties": collection_props,
        }

        self.add_layer(name, geojson, hoverable=hoverable)

    _template = """
                <div id="container" style="${container_style}; overflow:hidden; position:relative;">
                  <style>
                    /* Nicer draw vertices: circular, compact, with accent color */
                    .leaflet-editing-icon {
                      width: 10px !important;
                      height: 10px !important;
                      margin-left: -5px !important; /* center the handle */
                      margin-top: -5px !important;
                      border-radius: 50% !important;
                      background: #00bcd4 !important;
                      border: 2px solid #ffffff !important;
                      box-shadow: 0 0 0 2px rgba(0, 188, 212, 0.25) !important;
                    }
                    /* Midpoint handles slightly smaller and lighter */
                    .leaflet-editing-icon.leaflet-middle-marker-icon {
                      width: 8px !important;
                      height: 8px !important;
                      margin-left: -4px !important;
                      margin-top: -4px !important;
                      background: #80deea !important;
                      box-shadow: 0 0 0 2px rgba(128, 222, 234, 0.25) !important;
                    }
                    /* Refine draw toolbar buttons */
                    .leaflet-draw-toolbar .leaflet-bar a {
                      border-radius: 6px !important;
                      border-color: #e0e0e0 !important;
                      background-color: rgba(255, 255, 255, 0.95) !important;
                    }
                    .leaflet-draw-toolbar .leaflet-bar a:hover {
                      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15) !important;
                    }
                    /* Softer draw tooltip */
                    .leaflet-draw-tooltip {
                      border-radius: 6px !important;
                      background: rgba(0, 0, 0, 0.75) !important;
                      color: #fff !important;
                      padding: 4px 8px !important;
                      border: none !important;
                      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2) !important;
                    }
                  </style>
                  <div id="map" style="width:100%; height:100%;"></div>
                </div>
            """

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
        "https://cdn.jsdelivr.net/npm/leaflet.path.drag@0.0.6/src/Path.Drag.min.js",
        "https://api.mapbox.com/mapbox.js/plugins/leaflet-fullscreen/v1.0.1/Leaflet.fullscreen.min.js",
    ]


import numpy as np

pn.extension("leaflet")


def create_example_app(n: int = 20000) -> pn.Row:
    lat = 37.3 + 0.1 * np.sin(np.linspace(0, 2 * np.pi, n))
    lon = -122.0 + 0.1 * np.cos(np.linspace(0, 2 * np.pi, n))

    leaf = LeafletCanvasScatter(
        cmap="Inferno",
        container_style="width:600px;height:500px;border:1px solid gray;",
        show_hover=True,
    )

    leaf.add_scatter(
        name="Example Scatter",
        lats=list(map(float, lat)),
        lons=list(map(float, lon)),
        values=list(map(float, np.linspace(-1, 1, n))),
        cmap="Viridis",
        radius=3,
        fill_opacity=0.8,
        hoverable=True,
    )

    leaf.add_scatter(
        name="Example Scatter 2",
        lats=list(map(float, lat + 0.1)),
        lons=list(map(float, lon + 0.1)),
        cmap="blue",
        radius=3,
        fill_opacity=0.8,
        hoverable=True,
    )

    leaf.add_scatter(
        name="Example Scatter 3 - no hover",
        lats=list(map(float, lat + 0.2)),
        lons=list(map(float, lon + 0.2)),
        values=list(map(float, np.random.rand(n) * 100)),
        cmap="Inferno",
        radius=3,
        fill_opacity=0.8,
        hoverable=False,
    )

    shapes_pane = pn.pane.JSON(pn.bind(lambda s: s, leaf.param.drawn_shapes), depth=3)
    return pn.Row(leaf, shapes_pane)


app = create_example_app()
app.servable()
