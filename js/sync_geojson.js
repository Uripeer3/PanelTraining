function syncGeojson(self, data, state) {
    // Synchronize overlay layers from Python to Leaflet.
    // Python provides two dicts: geojson_overlays (static) and geojson_hover_overlays (participate in hover).
    // We merge them, create/update/remove Leaflet layers accordingly, then refresh the hover index.

    // Ensure the overlay bookkeeping and control exist.
    if (!state.geojsonLayers) {
        state.geojsonLayers = {};    // name -> Leaflet layer currently on the map
        state.geojsonData = {};      // name -> serialized JSON (only re-create when content actually changes)
        state.geojsonHoverable = {}; // name -> boolean (should points from this layer be used for hover snapping?)
        state.geojsonControl = L.control.layers(null, {}, {position: 'topright', collapsed: false}).addTo(state.map);
    }

    // Combine non-hoverable and hoverable dicts from Python.
    const staticDict = (data.geojson_overlays || {});
    const hoverDict = (data.geojson_hover_overlays || {});

    // Build the authoritative merged view:
    // - If a name exists in both, treat it as hoverable (hover overlay wins).
    const desired = {};
    for (const [k, v] of Object.entries(staticDict)) desired[k] = {geojson: v, hoverable: false};
    for (const [k, v] of Object.entries(hoverDict)) desired[k] = {geojson: v, hoverable: true};

    const desiredNames = new Set(Object.keys(desired));

    // Remove overlays no longer present
    for (const name of Object.keys(state.geojsonLayers)) {
        if (!desiredNames.has(name)) {
            const lyr = state.geojsonLayers[name];
            try {
                state.map.removeLayer(lyr);
            } catch (e) {
            }
            try {
                state.geojsonControl.removeLayer(lyr);
            } catch (e) {
            }
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
            try {
                state.map.removeLayer(old);
            } catch (e) {
            }
            try {
                state.geojsonControl.removeLayer(old);
            } catch (e) {
            }
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
                                try {
                                    const c = chroma(cmap);
                                    scale = chroma.scale(['#000000', c.hex()]);
                                } catch (e) {
                                    scale = chroma.scale(['#4575b4', '#ffffbf', '#d73027']);
                                }
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
                const allowed = ['color', 'weight', 'opacity', 'fillColor', 'fillOpacity', 'dashArray', 'lineCap', 'lineJoin'];
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

}

syncGeojson(self, data, state);
