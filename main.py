import panel as pn
import param
from panel.reactive import ReactiveHTML


class LeafletCanvasScatter(ReactiveHTML):
    """Leaflet map with chroma.js colormap + Canvas-Scatter for high-performance scatter, with draw + measure + fullscreen."""

    # Data/state
    center = param.XYCoordinates(default=(37.0, -122.0))
    zoom = param.Integer(default=9, bounds=(1, 22))
    cmap = param.String(default="Viridis")
    show_hover = param.Boolean(default=False)
    map_options = param.Dict(default={})  # Optional Leaflet L.map options (camelCase), merged with defaults in JS

    container_style = param.String(default="width:100%;height:100%;")
    tile_layers = param.Dict(default={
        "OSM": ("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                {"attribution": "&copy; OSM contributors"}),
        "Topo": ("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
                 {"attribution": "&copy; OpenTopoMap contributors"})
    })

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
            self, name: str, lats, lons, values=None, cmap=None, radius: int = 3, fill_opacity: float = 0.8,
            hoverable=False
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
            "fillOpacity": float(fill_opacity)  # Leaflet option key casing
        }
        if values is not None:
            collection_props.update({
                "vmin": vmin,
                "vmax": vmax,
                "cmap": cmap_val
            })
        else:
            collection_props.update({
                "color": cmap_val
            })

        features = []
        if values is not None:
            for i in range(n):
                # Only value is per-point; other styling lives at collection level
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lons[i], lats[i]]},
                    "properties": {"value": values[i]}
                })
        else:
            for i in range(n):
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lons[i], lats[i]]},
                    "properties": {}
                })

        geojson = {"type": "FeatureCollection", "features": features, "properties": collection_props}

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
        'render': """
            /*
             Plain-language guide to this JavaScript (for non-JS readers)

             - data: mirror of Python parameters (param) sent to the browser. Reading is cheap; writing back
                     to data.<name> pushes updates to Python (e.g., data.drawn_shapes = [...]).
             - state: persistent storage for this component on the browser. We put the map object, layers,
                      and helper functions here so they survive re-renders.
             - self:  lets us call other scripts declared in _scripts by name (e.g., self.sync_geojson()).

             Leaflet glossary:
             - LatLng: a latitude/longitude pair
             - Layer: a visual thing on the map (tile background, vector shapes, markers, etc.)
             - FeatureGroup: a collection of layers that can be edited/removed together
             - containerPoint: x/y pixel position relative to the map container (used for fast nearest-point checks)
             - renderer: tells Leaflet how to draw vectors; we use Canvas for performance
            */

            // 1) Create and configure the map
            // preferCanvas = faster vector rendering; we default to no native zoomControl but allow override via data.map_options
            const defaultMapOpts = { preferCanvas: true, zoomControl: false };
            const userMapOpts = (data.map_options || {});
            const mapOpts = Object.assign({}, defaultMapOpts, userMapOpts);
            state.map = L.map(map, mapOpts)
                        .setView([data.center[0], data.center[1]], data.zoom);

            // Shared Canvas renderer for fast point/vector drawing
            state.canvasRenderer = L.canvas({ padding: 0.5 });

            // 2) Add base layers (background map)
            // tile_layers (from Python) looks like: { "OSM": [urlTemplate, options], ... }
            state.baseLayers = {};
            for (const [name, entry] of Object.entries(data.tile_layers)) {
                const [url, opts] = entry;           // url has {z}/{x}/{y} placeholders
                state.baseLayers[name] = L.tileLayer(url, opts);  // opts contains attribution and other settings
            }
            // Put the first base layer on the map and expose a switcher
            const firstLayer = Object.values(state.baseLayers)[0];
            firstLayer.addTo(state.map);
            state.map.addControl(new L.control.layers(state.baseLayers, {}, { position: 'bottomright', collapsed: true }));

            // 3) Overlay bookkeeping (driven by Python dicts): one control for all overlays
            state.geojsonLayers = {};   // name -> Leaflet layer
            state.geojsonData = {};     // name -> serialized JSON (for change detection)
            state.geojsonControl = L.control.layers(null, {}, { position: 'topright', collapsed: false }).addTo(state.map);

            // When the user toggles overlays, recompute which points can be hovered/snapped
            if (!state.overlayEventsBound) {
                state.map.on('overlayadd',    () => self.sync_geojson());
                state.map.on('overlayremove', () => self.sync_geojson());
                state.overlayEventsBound = true;
            }

            // 4) Common map UI controls
            // Scale bar (metric only)
            state.map.addControl(L.control.scale({ position: 'bottomleft', imperial: false, metric: true }));
            // Only add a custom zoom control if native zoomControl is not enabled
            state.map.addControl(new L.Control.Fullscreen({ position: 'bottomleft', forceSeparateButton: false })); // fullscreen button
            if (!mapOpts.zoomControl) {
                state.map.addControl(new L.control.zoom({ position: 'bottomleft' }));   // zoom in/out
            }
            // Distance/area measurement tool
            state.measure = new L.Control.Measure({
                primaryLengthUnit: 'meters',
                secondaryLengthUnit: 'kilometers',
                primaryAreaUnit: 'sqmeters',
                secondaryAreaUnit: 'sqkilometers',
                position: 'bottomright'
            });
            state.map.addControl(state.measure);

            // 5) Drawing tools (polygons, circles, etc.)
            // We store user-drawn shapes in a FeatureGroup so they can be edited/removed as a set.
            state.drawnItems = new L.FeatureGroup().addTo(state.map);
            state.drawControl = new L.Control.Draw({
                position: 'topleft',
                edit: { featureGroup: state.drawnItems },
                draw: {
                    polygon: true,
                    polyline: false,
                    rectangle: false,
                    circle: true,
                    marker: false,
                    circlemarker: false
                }
            });
            state.map.addControl(state.drawControl);

            // Sync draw events back to Python: convert to GeoJSON on every change
            state.map.on(L.Draw.Event.CREATED, function (e) {
                // Add the new shape to the edit group and append its GeoJSON to Python's list
                state.drawnItems.addLayer(e.layer);
                data.drawn_shapes = [...data.drawn_shapes, e.layer.toGeoJSON()];
            });
            state.map.on('draw:deleted', function (e) {
                // Replace Python-side list with the remaining shapes
                data.drawn_shapes = state.drawnItems.toGeoJSON().features;
            });
            state.map.on('draw:edited', function (e) {
                // Replace Python-side list with the updated shapes
                data.drawn_shapes = state.drawnItems.toGeoJSON().features;
            });

            // 6) Hover marker + nearest-point snapping across overlays
            // A reusable "hover" circle marker: hidden until the mouse is close to a hoverable point.
            state.hover = L.circleMarker(
                [0, 0],
                { radius: 8, color: 'red', opacity: 0.9, interactive: false, renderer: state.canvasRenderer }
            );

            // Hover configuration/index
            state.hoverThresholdPx = 25;             // max pixel distance to snap
            state.gridCell = state.hoverThresholdPx; // grid size for spatial index in pixels
            state.hoverIndex = null;                 // Map: "cx:cy" -> array of {x, y, latlng}
            state.hoverIndexBounds = null;           // Optional bounds of the index
            state.geojsonHoverable = state.geojsonHoverable || {};

            // requestAnimationFrame throttle for mousemove (avoids excessive work)
            state._mmPending = false;
            state._mmLast = null;

            /**
             * Mouse-move handler that snaps the hover marker to the nearest point (if close enough).
             * @param {L.LeafletMouseEvent} ev
             */
            state.onMouseMove = function (ev) {
                if (!data.show_hover || !state.hoverIndex) return;
                state._mmLast = ev;
                if (state._mmPending) return;
                state._mmPending = true;

                requestAnimationFrame(() => {
                    state._mmPending = false;
                    const e = state._mmLast;
                    if (!e) return;

                    // Convert mouse lat/lon to pixel coordinates relative to the map container
                    const p = state.map.latLngToContainerPoint(e.latlng);
                    const cell = state._cellKeyFromPoint(p);
                    let best = null, bestDist = Infinity;

                    // Search the 3x3 neighborhood around the pointer's grid cell for the nearest point
                    for (let dy = -1; dy <= 1; dy++) {
                        for (let dx = -1; dx <= 1; dx++) {
                            const k = (cell.cx + dx) + ':' + (cell.cy + dy);
                            const arr = state.hoverIndex.get(k);
                            if (!arr) continue;
                            for (const o of arr) {
                                const dxp = p.x - o.x, dyp = p.y - o.y;
                                const d = Math.sqrt(dxp * dxp + dyp * dyp);
                                if (d < bestDist) { bestDist = d; best = o.latlng; }
                            }
                        }
                    }

                    // Show/hide the hover marker depending on distance
                    if (best && bestDist <= state.hoverThresholdPx) {
                        state.hover.setLatLng(best);
                        if (!state.map.hasLayer(state.hover)) state.map.addLayer(state.hover);
                    } else {
                        if (state.map.hasLayer(state.hover)) state.map.removeLayer(state.hover);
                    }
                });
            };
            state.map.on('mousemove', state.onMouseMove);

            /**
             * Convert a pixel point to a grid cell key used by the hover index.
             * @param {{x:number, y:number}} pt
             * @returns {{cx:number, cy:number, key:string}}
             */
            state._cellKeyFromPoint = function (pt) {
                const cx = Math.floor(pt.x / state.gridCell);
                const cy = Math.floor(pt.y / state.gridCell);
                return { cx, cy, key: cx + ':' + cy };
            };

            /**
             * Rebuild the hover spatial index from currently visible, hoverable layers.
             * Speeds up nearest-point queries by grouping points into grid cells.
             */
            state._rebuildHoverIndex = function () {
                const idx = new Map();
                let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;

                for (const [nm, lyr] of Object.entries(state.geojsonLayers)) {
                    if (!state.geojsonHoverable[nm]) continue;        // only hoverable overlays
                    if (!state.map.hasLayer(lyr)) continue;           // only visible overlays
                    try {
                        lyr.eachLayer(function (sub) {
                            if (sub && typeof sub.getLatLng === 'function') {
                                const ll = sub.getLatLng();
                                const pt = state.map.latLngToContainerPoint(ll);
                                if (!isFinite(pt.x) || !isFinite(pt.y)) return;
                                const cell = state._cellKeyFromPoint(pt);
                                if (!idx.has(cell.key)) idx.set(cell.key, []);
                                idx.get(cell.key).push({ x: pt.x, y: pt.y, latlng: ll });
                                if (pt.x < minX) minX = pt.x; if (pt.x > maxX) maxX = pt.x;
                                if (pt.y < minY) minY = pt.y; if (pt.y > maxY) maxY = pt.y;
                            }
                        });
                    } catch (e) { /* ignore errors from non-point layers */ }
                }

                state.hoverIndex = idx;
                state.hoverIndexBounds = { minX, maxX, minY, maxY };
            };

            // Rebuild index when zooming/moving (coordinates <-> pixels change)
            state.map.on('zoomend', () => state._rebuildHoverIndex());
            state.map.on('moveend', () => state._rebuildHoverIndex());
        """,

        'after_layout': """
            // This runs after Panel/Bokeh finishes placing and sizing the widget on the page.
            // Leaflet needs to be told when its container size might have changed:
            //   - invalidateSize() forces Leaflet to recompute the map's pixel size and re-render tiles/vectors.
            state.map.invalidateSize();

            // Keep the map correct if the browser window is resized later (e.g., user drags window edges).
            window.addEventListener('resize', () => state.map.invalidateSize());

            // Make sure our overlays (provided from Python) are added/updated at least once on first render.
            self.sync_geojson();

            // Ensure the hover marker visibility matches the current "show_hover" setting.
            self.show_hover();
        """,

        'show_hover': """
            // Show/hide the reusable hover marker based on Python's "show_hover" flag.
            // When enabled, the actual placement is handled by the mousemove handler in 'render'.
            if (!data.show_hover) {
                if (state.map.hasLayer(state.hover)) state.map.removeLayer(state.hover);
                return;
            }
            // If enabled, do nothing here; movement is handled by mouse events.
            return;
        """,

        # Shared sync that reads BOTH overlay params and updates the map/control
        'sync_geojson': """
            // Synchronize overlay layers from Python to Leaflet.
            // Python provides two dicts: geojson_overlays (static) and geojson_hover_overlays (participate in hover).
            // We merge them, create/update/remove Leaflet layers accordingly, then refresh the hover index.

            // Ensure the overlay bookkeeping and control exist.
            if (!state.geojsonLayers) {
                state.geojsonLayers = {};    // name -> Leaflet layer currently on the map
                state.geojsonData = {};      // name -> serialized JSON (only re-create when content actually changes)
                state.geojsonHoverable = {}; // name -> boolean (should points from this layer be used for hover snapping?)
                state.geojsonControl = L.control.layers(null, {}, { position: 'topright', collapsed: false }).addTo(state.map);
            }

            // Combine non-hoverable and hoverable dicts from Python.
            const staticDict = (data.geojson_overlays || {});
            const hoverDict  = (data.geojson_hover_overlays || {});

            // Build the authoritative merged view:
            // - If a name exists in both, treat it as hoverable (hover overlay wins).
            const desired = {};
            for (const [k, v] of Object.entries(staticDict)) desired[k] = { geojson: v, hoverable: false };
            for (const [k, v] of Object.entries(hoverDict))  desired[k] = { geojson: v, hoverable: true  };

            const desiredNames = new Set(Object.keys(desired));

            // Remove overlays no longer present
            for (const name of Object.keys(state.geojsonLayers)) {
                if (!desiredNames.has(name)) {
                    const lyr = state.geojsonLayers[name];
                    try { state.map.removeLayer(lyr); } catch (e) {}
                    try { state.geojsonControl.removeLayer(lyr); } catch (e) {}
                    delete state.geojsonLayers[name];
                    delete state.geojsonData[name];
                    delete state.geojsonHoverable[name];
                }
            }

            // Add or update overlays
            let changedVisiblePoints = false;
            for (const [name, entry] of Object.entries(desired)) {
                const gj = entry && entry.geojson !== undefined ? entry.geojson : entry;
                const hoverable = !!(entry && entry.hoverable);

                // Use stringify for content-change detection
                const serialized = JSON.stringify(gj);
                const needsCreate = !(name in state.geojsonLayers)
                                    || state.geojsonData[name] !== serialized
                                    || state.geojsonHoverable[name] !== hoverable;
                if (!needsCreate) continue;

                // Remove previous layer if present
                if (state.geojsonLayers[name]) {
                    const old = state.geojsonLayers[name];
                    try { state.map.removeLayer(old); } catch (e) {}
                    try { state.geojsonControl.removeLayer(old); } catch (e) {}
                }

                const collectionProps = (gj && gj.properties) ? gj.properties : {};

                // Pre-configured canvas renderer and non-interactive shapes
                const layer = L.geoJSON(gj, {
                    pointToLayer: function (feature, latlng) {
                        const p = feature.properties || {};
                        // Merge: collection-level props as defaults, then per-feature
                        const baseOpts = {
                            radius: 3,
                            weight: 0,
                            interactive: false,
                            renderer: state.canvasRenderer
                        };
                        const merged = Object.assign({}, baseOpts, collectionProps, p);

                        // Color handling:
                        // - per-feature color wins
                        // - else collection-level color
                        // - else auto from value + collection vmin/vmax/cmap
                        let colorToUse = merged.color || merged.fillColor || null;
                        if (!colorToUse) {
                            const v = (p.value !== undefined) ? p.value : undefined;
                            const vmin = (collectionProps.vmin !== undefined) ? collectionProps.vmin : p.vmin;
                            const vmax = (collectionProps.vmax !== undefined) ? collectionProps.vmax : p.vmax;
                            const cmap = (collectionProps.cmap !== undefined) ? collectionProps.cmap : p.cmap;
                            if (v !== undefined && vmin !== undefined && vmax !== undefined && cmap !== undefined) {
                                const brewer = chroma.brewer || {};
                                const tryBrewer = (key) => (key && key in brewer) ? chroma.scale(brewer[key]) : null;
                                let scale;
                                if (Array.isArray(cmap)) {
                                    scale = chroma.scale(cmap);
                                } else if (typeof cmap === 'string') {
                                    scale = tryBrewer(cmap) || tryBrewer((cmap || '').toLowerCase());
                                    if (!scale) {
                                        try { const c = chroma(cmap); scale = chroma.scale(['#000000', c.hex()]); }
                                        catch (e) { scale = chroma.scale(['#4575b4', '#ffffbf', '#d73027']); }
                                    }
                                } else {
                                    scale = chroma.scale(['#4575b4', '#ffffbf', '#d73027']);
                                }
                                scale = scale.domain([vmin, vmax]);
                                colorToUse = scale(v).hex();
                            } else {
                                colorToUse = '#1f77b4';
                            }
                        }

                        // Leaflet style casing: fillOpacity not fill_opacity
                        const opts = Object.assign({}, merged);
                        if (!opts.color) opts.color = colorToUse;
                        if (!opts.fillColor) opts.fillColor = colorToUse;

                        return L.circleMarker(latlng, opts);
                    },
                    style: function (feature) {
                        const p = feature.properties || {};
                        const cp = collectionProps || {};
                        const allowed = ['color','weight','opacity','fillColor','fillOpacity','dashArray','lineCap','lineJoin'];
                        const s = {};
                        for (const k of allowed) {
                            if (p[k] !== undefined) s[k] = p[k];
                            else if (cp[k] !== undefined) s[k] = cp[k];
                        }
                        if (Object.keys(s).length === 0) {
                            s.color = '#3388ff';
                            s.weight = 2;
                            s.fillOpacity = 0.2;
                        }
                        // Ensure canvas renderer for vector shapes
                        s.renderer = state.canvasRenderer;
                        return s;
                    }
                });

                layer.addTo(state.map);
                state.geojsonLayers[name] = layer;
                state.geojsonData[name] = serialized;
                state.geojsonHoverable[name] = hoverable;
                state.geojsonControl.addOverlay(layer, name);
                changedVisiblePoints = true;
            }

            // Rebuild the hover grid index to reflect current visibility and geometry
            state._rebuildHoverIndex();
        """,

        # Trigger sync whenever either param changes
        'geojson_overlays': "self.sync_geojson()",
        'geojson_hover_overlays': "self.sync_geojson()",

    }
    _extension_name = 'leaflet'

    __css__ = [
        'https://unpkg.com/leaflet@1.7.1/dist/leaflet.css',
        'https://unpkg.com/leaflet-draw/dist/leaflet.draw.css',
        'https://unpkg.com/leaflet-measure/dist/leaflet-measure.css',
        'https://api.mapbox.com/mapbox.js/plugins/leaflet-fullscreen/v1.0.1/leaflet.fullscreen.css',
    ]
    __javascript__ = [
        'https://unpkg.com/leaflet@1.7.1/dist/leaflet.js',
        'https://unpkg.com/chroma-js@2.4.2/chroma.min.js',
        'https://unpkg.com/leaflet-draw/dist/leaflet.draw.js',
        'https://unpkg.com/leaflet-measure/dist/leaflet-measure.js',
        'https://api.mapbox.com/mapbox.js/plugins/leaflet-fullscreen/v1.0.1/Leaflet.fullscreen.min.js',
        # Canvas-Scatter plugin
        'https://unpkg.com/leaflet-canvas-marker@0.2.0/dist/leaflet.canvas-markers.min.js'
    ]


import numpy as np

pn.extension('leaflet')

# Generate large dataset
n = 20000
lat = 37.3 + 0.1 * np.sin(np.linspace(0, 50 * np.pi, n))
lon = -122.0 + 0.1 * np.cos(np.linspace(0, 50 * np.pi, n))
values = np.random.rand(n) * 100

leaf = LeafletCanvasScatter(
    cmap="Inferno",
    container_style="width:600px;height:500px;border:1px solid gray;",
    show_hover=True,
)

# Example overlay: add a hoverable colored scatter built from the arrays above
leaf.add_scatter(
    name="Example Scatter",
    lats=list(map(float, lat)),
    lons=list(map(float, lon)),
    values=list(map(float, values)),
    cmap="Inferno",
    radius=3,
    fill_opacity=0.8,
    hoverable=True,
)
# Example overlay: add a hoverable colored scatter built from the arrays above
leaf.add_scatter(
    name="Example Scatter 2",
    lats=list(map(float, lat + 0.1)),
    lons=list(map(float, lon + 0.1)),
    values=list(map(float, values)),
    cmap="Inferno",
    radius=3,
    fill_opacity=0.8,
    hoverable=True,
)
# Example overlay: add a hoverable colored scatter built from the arrays above
leaf.add_scatter(
    name="Example Scatter 3 - no hover",
    lats=list(map(float, lat + 0.2)),
    lons=list(map(float, lon + 0.2)),
    values=list(map(float, values)),
    cmap="Inferno",
    radius=3,
    fill_opacity=0.8,
    hoverable=False,
)

shapes_pane = pn.pane.JSON(pn.bind(lambda s: s, leaf.param.drawn_shapes), depth=3)

pn.Row(leaf, shapes_pane).servable()
