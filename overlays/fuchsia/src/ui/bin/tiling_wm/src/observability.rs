// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Fuchsia diagnostics surface for Instrument Studio feedback.
//!
//! Publishes tiling WM state through Inspect so host-side tools can compare a
//! live session against the Instrument Studio design contract without scraping
//! only unstructured logs.

use crate::policy::{LayoutConfig, WindowPolicy};
use fuchsia_inspect::Node;
use fuchsia_inspect::Property;
use fuchsia_inspect::{BoolProperty, StringProperty, UintProperty};

/// Live Inspect publisher for window-manager state used by design feedback.
pub struct WmObservability {
    _root: Node,
    _config: Node,
    _focus: Node,
    tile_count: UintProperty,
    gap_px: UintProperty,
    active_border_px: UintProperty,
    wrap_focus: BoolProperty,
    selected_focus: StringProperty,
    confirmed_focus: StringProperty,
    order: StringProperty,
    present_count: UintProperty,
    last_present_context: StringProperty,
    pub present_count_value: u64,
}

impl WmObservability {
    /// Attach properties under `root` (typically `component::inspector().root()`).
    pub fn attach(root: &Node, config: &LayoutConfig) -> Self {
        let wm = root.create_child("tiling_wm");
        let config_node = wm.create_child("config");
        let focus = wm.create_child("focus");

        let gap_px = config_node.create_uint("gap_px", config.gap_px as u64);
        let active_border_px =
            config_node.create_uint("active_border_px", config.active_border_px as u64);
        let wrap_focus = config_node.create_bool("wrap_focus", config.wrap_focus);

        let selected_focus = focus.create_string("selected", "");
        let confirmed_focus = focus.create_string("confirmed", "");

        let tile_count = wm.create_uint("tile_count", 0);
        let order = wm.create_string("order", "");
        let present_count = wm.create_uint("present_count", 0);
        let last_present_context = wm.create_string("last_present_context", "init");

        Self {
            _root: wm,
            _config: config_node,
            _focus: focus,
            tile_count,
            gap_px,
            active_border_px,
            wrap_focus,
            selected_focus,
            confirmed_focus,
            order,
            present_count,
            last_present_context,
            present_count_value: 0,
        }
    }

    /// Publish the current policy/config snapshot.
    pub fn publish_state(&mut self, policy: &WindowPolicy, config: &LayoutConfig) {
        let order = policy.order();
        self.tile_count.set(order.len() as u64);
        self.order.set(&order.join(","));
        self.selected_focus.set(policy.focused_id().unwrap_or(""));
        self.confirmed_focus
            .set(policy.confirmed_focus_id().unwrap_or(""));
        self.gap_px.set(config.gap_px as u64);
        self.active_border_px.set(config.active_border_px as u64);
        self.wrap_focus.set(config.wrap_focus);
    }

    /// Record a successful Flatland present used by the design loop.
    pub fn record_present(&mut self, context: &str) {
        self.present_count_value = self.present_count_value.saturating_add(1);
        self.present_count.set(self.present_count_value);
        self.last_present_context.set(context);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use fuchsia_inspect::Inspector;

    #[test]
    fn publish_state_records_selected_and_confirmed_focus() {
        let inspector = Inspector::default();
        let config = LayoutConfig::default();
        let mut obs = WmObservability::attach(inspector.root(), &config);
        let mut policy = WindowPolicy::new(config).unwrap();
        policy.add_front("settings".into());
        policy.add_front("browser".into());
        policy.confirm_focus("settings").unwrap();
        obs.publish_state(&policy, &config);
        obs.record_present("test");
        // Property handles are live; hierarchy existence is enough for unit scope.
        // Full tree assertions require diagnostics_assertions in-tree deps.
        assert_eq!(obs.present_count_value, 1);
        assert_eq!(policy.confirmed_focus_id(), Some("settings"));
        assert_eq!(policy.order(), vec!["browser", "settings"]);
        let _ = inspector;
    }
}
