// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Instrument Studio chrome bars owned by the tiling WM root view.

use anyhow::{Context, Error};
use desktop_ui::{ChromeRegion, InstrumentStudioLayout};
use fidl_fuchsia_math as fmath;
use fidl_fuchsia_ui_composition as ui_comp;
use fuchsia_scenic::flatland::IdGenerator;

struct Bar {
    transform: ui_comp::TransformId,
    content: ui_comp::ContentId,
}

impl Bar {
    fn create(
        flatland: &ui_comp::FlatlandProxy,
        ids: &mut IdGenerator,
        root: &ui_comp::TransformId,
    ) -> Result<Self, Error> {
        let transform = ids.next_transform_id();
        let content = ids.next_content_id();
        flatland.create_transform(&transform).context("chrome create transform")?;
        flatland.create_filled_rect(&content).context("chrome create rect")?;
        flatland.set_content(&transform, &content).context("chrome set content")?;
        flatland.add_child(root, &transform).context("chrome add child")?;
        Ok(Self { transform, content })
    }

    fn layout(
        &self,
        flatland: &ui_comp::FlatlandProxy,
        x: u32,
        y: u32,
        width: u32,
        height: u32,
        color: ui_comp::ColorRgba,
    ) -> Result<(), Error> {
        let width = width.max(1);
        let height = height.max(1);
        flatland
            .set_solid_fill(&self.content, &color, &fmath::SizeU { width, height })
            .context("chrome solid fill")?;
        flatland
            .set_translation(&self.transform, &fmath::Vec_ { x: x as i32, y: y as i32 })
            .context("chrome translate")?;
        Ok(())
    }
}

/// Persistent shell chrome attached under the WM root transform.
pub struct ShellChrome {
    strip: Bar,
    strip_accent: Bar,
    rail: Bar,
    rail_accent: Bar,
    inspector: Bar,
    inspector_accent: Bar,
}

impl ShellChrome {
    pub fn create(
        flatland: &ui_comp::FlatlandProxy,
        ids: &mut IdGenerator,
        root: &ui_comp::TransformId,
    ) -> Result<Self, Error> {
        Ok(Self {
            strip: Bar::create(flatland, ids, root)?,
            strip_accent: Bar::create(flatland, ids, root)?,
            rail: Bar::create(flatland, ids, root)?,
            rail_accent: Bar::create(flatland, ids, root)?,
            inspector: Bar::create(flatland, ids, root)?,
            inspector_accent: Bar::create(flatland, ids, root)?,
        })
    }

    pub fn layout(
        &self,
        flatland: &ui_comp::FlatlandProxy,
        shell: &InstrumentStudioLayout,
    ) -> Result<(), Error> {
        let theme = shell.theme;
        let strip = shell.region_rect(ChromeRegion::WorkspaceStrip);
        let rail = shell.region_rect(ChromeRegion::LauncherRail);
        let inspector = shell.region_rect(ChromeRegion::Inspector);

        let panel = ui_comp::ColorRgba {
            red: theme.panel_elevated.red,
            green: theme.panel_elevated.green,
            blue: theme.panel_elevated.blue,
            alpha: theme.panel_elevated.alpha,
        };
        let panel_bg = ui_comp::ColorRgba {
            red: theme.panel_bg.red,
            green: theme.panel_bg.green,
            blue: theme.panel_bg.blue,
            alpha: theme.panel_bg.alpha,
        };
        let cyan = ui_comp::ColorRgba {
            red: theme.confirmed_focus.red,
            green: theme.confirmed_focus.green,
            blue: theme.confirmed_focus.blue,
            alpha: theme.confirmed_focus.alpha,
        };
        let violet = ui_comp::ColorRgba {
            red: theme.accent_secondary.red,
            green: theme.accent_secondary.green,
            blue: theme.accent_secondary.blue,
            alpha: theme.accent_secondary.alpha,
        };

        self.strip.layout(flatland, strip.x, strip.y, strip.width, strip.height, panel)?;
        // Cyan underline under workspace strip.
        self.strip_accent.layout(
            flatland,
            strip.x,
            strip.y + strip.height.saturating_sub(3),
            strip.width,
            3,
            cyan,
        )?;

        self.rail.layout(flatland, rail.x, rail.y, rail.width, rail.height, panel_bg)?;
        // Violet edge on rail.
        self.rail_accent.layout(
            flatland,
            rail.x + rail.width.saturating_sub(3),
            rail.y,
            3,
            rail.height,
            violet,
        )?;

        self.inspector.layout(
            flatland,
            inspector.x,
            inspector.y,
            inspector.width,
            inspector.height,
            panel,
        )?;
        // Cyan top edge on inspector.
        self.inspector_accent.layout(flatland, inspector.x, inspector.y, inspector.width, 3, cyan)?;
        Ok(())
    }
}
