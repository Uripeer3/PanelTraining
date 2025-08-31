function afterLayout(self, data, state) {
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
        
}
afterLayout(self, data, state);
