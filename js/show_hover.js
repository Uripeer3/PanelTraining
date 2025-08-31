function showHover(self, data, state) {
            // Show/hide the reusable hover marker based on Python's "show_hover" flag.
            // When enabled, the actual placement is handled by the mousemove handler in 'render'.
            if (!data.show_hover) {
                if (state.map.hasLayer(state.hover)) state.map.removeLayer(state.hover);
                return;
            }
            // If enabled, do nothing here; movement is handled by mouse events.
            return;
        
}
showHover(self, data, state);
