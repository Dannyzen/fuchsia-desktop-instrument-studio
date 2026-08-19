// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Chrome regions for the Instrument Studio shell.

use crate::tokens::{ThemeTokens, INSTRUMENT_STUDIO_THEME};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ChromeRegion {
    WorkspaceStrip,
    LauncherRail,
    TiledStage,
    Inspector,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct WorkspaceId(pub u8);

#[derive(Clone, Debug, PartialEq)]
pub struct InstrumentStudioLayout {
    pub width: u32,
    pub height: u32,
    pub theme: ThemeTokens,
    pub active_workspace: WorkspaceId,
    pub workspaces: Vec<WorkspaceId>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rect {
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
}

impl InstrumentStudioLayout {
    pub fn new(width: u32, height: u32) -> Result<Self, String> {
        // Emulator FEMU often boots portrait (e.g. 720x1200). Keep chrome usable there.
        if width < 640 || height < 480 {
            return Err(format!("instrument studio needs at least 640x480, got {width}x{height}"));
        }
        let mut theme = INSTRUMENT_STUDIO_THEME;
        // Shrink chrome on narrow/short displays so the stage remains usable.
        if width < 900 {
            theme.rail_width_px = theme.rail_width_px.min(56);
        }
        if height < 900 {
            // Keep strip/inspector tall enough for 4px bitmap labels on FEMU.
            theme.panel_height_px = theme.panel_height_px.min(56).max(52);
            theme.inspector_height_px = theme.inspector_height_px.min(148).max(136);
        }
        Ok(Self {
            width,
            height,
            theme,
            active_workspace: WorkspaceId(1),
            workspaces: vec![WorkspaceId(1), WorkspaceId(2), WorkspaceId(3)],
        })
    }

    pub fn region_rect(&self, region: ChromeRegion) -> Rect {
        let t = self.theme;
        match region {
            ChromeRegion::WorkspaceStrip => Rect {
                x: 0,
                y: 0,
                width: self.width,
                height: t.panel_height_px,
            },
            ChromeRegion::LauncherRail => Rect {
                x: 0,
                y: t.panel_height_px,
                width: t.rail_width_px,
                height: self
                    .height
                    .saturating_sub(t.panel_height_px + t.inspector_height_px),
            },
            ChromeRegion::Inspector => Rect {
                x: 0,
                y: self.height.saturating_sub(t.inspector_height_px),
                width: self.width,
                height: t.inspector_height_px,
            },
            ChromeRegion::TiledStage => Rect {
                x: t.rail_width_px,
                y: t.panel_height_px,
                width: self.width.saturating_sub(t.rail_width_px),
                height: self
                    .height
                    .saturating_sub(t.panel_height_px + t.inspector_height_px),
            },
        }
    }

    /// Stage size the tiling WM should treat as its root layout bounds
    /// once shell chrome is owned outside the WM.
    pub fn stage_size(&self) -> (u32, u32) {
        let stage = self.region_rect(ChromeRegion::TiledStage);
        (stage.width, stage.height)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn regions_cover_canvas_without_overlap_on_stage_edges() {
        let layout = InstrumentStudioLayout::new(1440, 900).unwrap();
        let strip = layout.region_rect(ChromeRegion::WorkspaceStrip);
        let rail = layout.region_rect(ChromeRegion::LauncherRail);
        let stage = layout.region_rect(ChromeRegion::TiledStage);
        let inspector = layout.region_rect(ChromeRegion::Inspector);

        assert_eq!(strip.y, 0);
        assert_eq!(rail.x, 0);
        assert_eq!(stage.x, rail.width);
        assert_eq!(stage.y, strip.height);
        assert_eq!(inspector.y + inspector.height, 900);
        assert_eq!(stage.width + rail.width, 1440);
        assert_eq!(strip.height + stage.height + inspector.height, 900);
    }

    #[test]
    fn rejects_tiny_displays() {
        assert!(InstrumentStudioLayout::new(640, 480).is_err());
    }
}
