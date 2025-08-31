function initializeMap(self, data, state) {
    // preferCanvas = faster vector rendering; we default to no native zoomControl but allow override via data.map_options
    const defaultMapOpts = {preferCanvas: true, zoomControl: false};
    const userMapOpts = (data.map_options || {});
    const mapOpts = Object.assign({}, defaultMapOpts, userMapOpts);
    state.map = L.map(map, mapOpts)
        .setView([data.center[0], data.center[1]], data.zoom);

    // Shared Canvas renderer for fast point/vector drawing
    state.canvasRenderer = L.canvas({padding: 0.5});

    addCommonControls(self, data, state, mapOpts);

}

function addCommonControls(self, data, state, mapOpts) {
    // Scale bar (metric only)
    state.map.addControl(L.control.scale({position: 'bottomleft', imperial: false, metric: true}));
    // Only add a custom zoom control if native zoomControl is not enabled
    state.map.addControl(new L.Control.Fullscreen({position: 'bottomleft', forceSeparateButton: false})); // fullscreen button
    if (!mapOpts.zoomControl) {
        state.map.addControl(new L.control.zoom({position: 'bottomleft'}));   // zoom in/out
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

}

function addBaseLayers(self, data, state) {
    // tile_layers (from Python) looks like: { "OSM": [urlTemplate, options], ... }
    state.baseLayers = {};
    for (const [name, entry] of Object.entries(data.tile_layers)) {
        const [url, opts] = entry;           // url has {z}/{x}/{y} placeholders
        state.baseLayers[name] = L.tileLayer(url, opts);  // opts contains attribution and other settings
    }
    // Put the first base layer on the map and expose a switcher
    const firstLayer = Object.values(state.baseLayers)[0];
    firstLayer.addTo(state.map);
    state.map.addControl(new L.control.layers(state.baseLayers, {}, {position: 'bottomright', collapsed: true}));

}

function configureOverlays(self, data, state) {
    state.geojsonLayers = {};   // name -> Leaflet layer
    state.geojsonData = {};     // name -> serialized JSON (for change detection)
    state.geojsonControl = L.control.layers(null, {}, {position: 'topright', collapsed: false}).addTo(state.map);

    // When the user toggles overlays, recompute which points can be hovered/snapped
    if (!state.overlayEventsBound) {
        state.map.on('overlayadd', () => self.sync_geojson());
        state.map.on('overlayremove', () => self.sync_geojson());
        state.overlayEventsBound = true;
    }

}


function setupDrawingTools(self, data, state) {
    // We store user-drawn shapes in a FeatureGroup so they can be edited/removed as a set.
    state.drawnItems = new L.FeatureGroup().addTo(state.map);
    state.geojsonControl.addOverlay(state.drawnItems, 'Drawn Shapes');
    state.drawControl = new L.Control.Draw({
        position: 'topleft',
        edit: {featureGroup: state.drawnItems},
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
    state.map.on('draw:editstart', function () {
        state.centroidHandles = [];

        state.drawnItems.eachLayer(function (layer) {
            if (layer instanceof L.Polygon) {

                let centroid = layer.getCenter();

                // Create draggable marker at centroid
                const handle = L.marker(centroid, {
                    draggable: true,
                    icon: L.divIcon({
                        className: 'polygon-drag-handle',
                        html: '<div style="width:12px;height:12px;background:#ff4081;border-radius:50%;border:2px solid white;box-shadow:0 0 4px rgba(0,0,0,0.5)"></div>',
                        iconSize: [12, 12]
                    })
                }).addTo(state.map);
                state.centroidHandles.push(handle);
                // Keep centroid handle updated when vertices move
                layer.on('edit', function () {
                    if (handle) {
                        const c = layer.getCenter();
                        handle.setLatLng(c);
                    }
                });

                handle.on('drag', function (ev) {
                    const newC = ev.latlng;
                    const oldC = centroid;
                    const dLat = newC.lat - oldC.lat;
                    const dLng = newC.lng - oldC.lng;

                    // In-place shift of existing vertices
                    const latlngs = layer.getLatLngs()[0];
                    for (let i = 0; i < latlngs.length; i++) {
                        latlngs[i].lat += dLat;
                        latlngs[i].lng += dLng;
                    }
                    layer.redraw();

                    // Now resync editing markers
                    if (layer.editing) {
                        layer.editing.updateMarkers();
                    }

                    // Update centroid ref
                    centroid = layer.getCenter();
                });

                handle.on('dragend', function () {
                    data.drawn_shapes = state.drawnItems.toGeoJSON().features;

                    // Recompute centroid and reset handle there
                    centroid = layer.getCenter();
                    handle.setLatLng(centroid);
                });
            }
        });
    });

    // Remove centroid handles when leaving edit mode
    state.map.on('draw:editstop', function () {
        if (state.centroidHandles) {
            for (const h of state.centroidHandles) {
                state.map.removeLayer(h);
            }
            state.centroidHandles = [];
        }
    });


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

}

function setupHover(self, data, state) {
    // A reusable "hover" circle marker: hidden until the mouse is close to a hoverable point.
    state.hover = L.circleMarker(
        [0, 0],
        {radius: 8, color: 'red', opacity: 0.9, interactive: false, renderer: state.canvasRenderer}
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
                        if (d < bestDist) {
                            bestDist = d;
                            best = o.latlng;
                        }
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

    // Hide hover marker when the cursor leaves the map area
    state.map.on('mouseout', function () {
        if (state.map.hasLayer(state.hover)) state.map.removeLayer(state.hover);
    });

    /**
     * Convert a pixel point to a grid cell key used by the hover index.
     * @param {{x:number, y:number}} pt
     * @returns {{cx:number, cy:number, key:string}}
     */
    state._cellKeyFromPoint = function (pt) {
        const cx = Math.floor(pt.x / state.gridCell);
        const cy = Math.floor(pt.y / state.gridCell);
        return {cx, cy, key: cx + ':' + cy};
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
                        idx.get(cell.key).push({x: pt.x, y: pt.y, latlng: ll});
                        if (pt.x < minX) minX = pt.x;
                        if (pt.x > maxX) maxX = pt.x;
                        if (pt.y < minY) minY = pt.y;
                        if (pt.y > maxY) maxY = pt.y;
                    }
                });
            } catch (e) { /* ignore errors from non-point layers */
            }
        }

        state.hoverIndex = idx;
        state.hoverIndexBounds = {minX, maxX, minY, maxY};
    };

    // Rebuild index when zooming/moving (coordinates <-> pixels change)
    state.map.on('zoomend', () => state._rebuildHoverIndex());
    state.map.on('moveend', () => state._rebuildHoverIndex());

}

function render(self, data, state) {
    initializeMap(self, data, state);
    addBaseLayers(self, data, state);
    configureOverlays(self, data, state);
    setupDrawingTools(self, data, state);
    setupHover(self, data, state);
}

render(self, data, state);
