// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Instrument Studio chrome owned by the tiling WM root view.
//!
//! Geometric density first (pills/marks/cards) so the shell reads as a product
//! even before glyph text lands in every region.

use anyhow::{Context, Error};
use desktop_ui::{ChromeRegion, InstrumentStudioLayout};
use fidl_fuchsia_math as fmath;
use fidl_fuchsia_ui_composition as ui_comp;
use fuchsia_scenic::flatland::IdGenerator;

#[derive(Clone, Debug, Default)]
pub struct ChromeState {
    pub tile_count: u32,
    pub confirmed_focus: String,
    pub order: Vec<String>,
    pub gap_px: u32,
    pub active_border_px: u32,
    pub present_count: u64,
}

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

fn rgba(r: f32, g: f32, b: f32, a: f32) -> ui_comp::ColorRgba {
    ui_comp::ColorRgba { red: r, green: g, blue: b, alpha: a }
}

/// Persistent shell chrome attached under the WM root transform.
pub struct ShellChrome {
    strip: Bar,
    strip_accent: Bar,
    brand: Bar,
    brand_dot: Bar,
    pills: [Bar; 3],
    pill_accents: [Bar; 3],
    status_chip: Bar,
    status_dot: Bar,
    rail: Bar,
    rail_accent: Bar,
    rail_icons: [Bar; 4],
    rail_icon_cores: [Bar; 4],
    inspector: Bar,
    inspector_accent: Bar,
    inspector_cards: [Bar; 4],
    inspector_card_bars: [Bar; 4],
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
            brand: Bar::create(flatland, ids, root)?,
            brand_dot: Bar::create(flatland, ids, root)?,
            pills: [
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
            ],
            pill_accents: [
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
            ],
            status_chip: Bar::create(flatland, ids, root)?,
            status_dot: Bar::create(flatland, ids, root)?,
            rail: Bar::create(flatland, ids, root)?,
            rail_accent: Bar::create(flatland, ids, root)?,
            rail_icons: [
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
            ],
            rail_icon_cores: [
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
            ],
            inspector: Bar::create(flatland, ids, root)?,
            inspector_accent: Bar::create(flatland, ids, root)?,
            inspector_cards: [
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
            ],
            inspector_card_bars: [
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
                Bar::create(flatland, ids, root)?,
            ],
        })
    }

    pub fn layout(
        &self,
        flatland: &ui_comp::FlatlandProxy,
        shell: &InstrumentStudioLayout,
        state: &ChromeState,
    ) -> Result<(), Error> {
        let theme = shell.theme;
        let strip = shell.region_rect(ChromeRegion::WorkspaceStrip);
        let rail = shell.region_rect(ChromeRegion::LauncherRail);
        let inspector = shell.region_rect(ChromeRegion::Inspector);

        let panel = rgba(
            theme.panel_elevated.red,
            theme.panel_elevated.green,
            theme.panel_elevated.blue,
            theme.panel_elevated.alpha,
        );
        let panel_bg =
            rgba(theme.panel_bg.red, theme.panel_bg.green, theme.panel_bg.blue, theme.panel_bg.alpha);
        let muted = rgba(
            theme.border_muted.red,
            theme.border_muted.green,
            theme.border_muted.blue,
            theme.border_muted.alpha,
        );
        let cyan = rgba(
            theme.confirmed_focus.red,
            theme.confirmed_focus.green,
            theme.confirmed_focus.blue,
            theme.confirmed_focus.alpha,
        );
        let violet = rgba(
            theme.accent_secondary.red,
            theme.accent_secondary.green,
            theme.accent_secondary.blue,
            theme.accent_secondary.alpha,
        );
        let ok = rgba(theme.ok.red, theme.ok.green, theme.ok.blue, theme.ok.alpha);
        let selected = rgba(
            theme.selected_focus.red,
            theme.selected_focus.green,
            theme.selected_focus.blue,
            theme.selected_focus.alpha,
        );

        // Workspace strip + accent.
        self.strip.layout(flatland, strip.x, strip.y, strip.width, strip.height, panel)?;
        self.strip_accent.layout(
            flatland,
            strip.x,
            strip.y + strip.height.saturating_sub(3),
            strip.width,
            3,
            cyan,
        )?;

        // Brand block (left).
        let brand_w = 34u32.min(strip.height.saturating_sub(10).max(20));
        let brand_x = strip.x + 10;
        let brand_y = strip.y + strip.height.saturating_sub(brand_w) / 2;
        self.brand.layout(flatland, brand_x, brand_y, brand_w, brand_w, muted)?;
        self.brand_dot.layout(
            flatland,
            brand_x + brand_w / 4,
            brand_y + brand_w / 4,
            brand_w / 2,
            brand_w / 2,
            cyan,
        )?;

        // Three workspace pills: Build / Research / Ops (active = first for now).
        let pill_h = strip.height.saturating_sub(14).max(18);
        let pill_w = if strip.width < 800 { 54 } else { 72 };
        let mut px = brand_x + brand_w + 12;
        let py = strip.y + strip.height.saturating_sub(pill_h) / 2;
        for i in 0..3 {
            let active = i == 0;
            let fill = if active { selected } else { panel_bg };
            self.pills[i].layout(flatland, px, py, pill_w, pill_h, fill)?;
            self.pill_accents[i].layout(
                flatland,
                px,
                py + pill_h.saturating_sub(3),
                pill_w,
                3,
                if active { cyan } else { muted },
            )?;
            px += pill_w + 8;
        }

        // Status chip on the right: green when healthy tiles present.
        let chip_w = if strip.width < 800 { 48 } else { 64 };
        let chip_h = pill_h;
        let chip_x = strip.x + strip.width.saturating_sub(chip_w + 12);
        let chip_y = py;
        self.status_chip.layout(flatland, chip_x, chip_y, chip_w, chip_h, panel_bg)?;
        let dot = 10u32;
        self.status_dot.layout(
            flatland,
            chip_x + 10,
            chip_y + chip_h.saturating_sub(dot) / 2,
            dot,
            dot,
            if state.tile_count > 0 { ok } else { muted },
        )?;

        // Launcher rail + violet edge.
        self.rail.layout(flatland, rail.x, rail.y, rail.width, rail.height, panel_bg)?;
        self.rail_accent.layout(
            flatland,
            rail.x + rail.width.saturating_sub(3),
            rail.y,
            3,
            rail.height,
            violet,
        )?;

        // Four app marks on rail (browser/terminal/files/settings style).
        let icon = rail.width.saturating_sub(18).clamp(22, 36);
        let gap = 14u32;
        let mut iy = rail.y + 16;
        let ix = rail.x + rail.width.saturating_sub(icon) / 2;
        let active_idx = active_rail_index(state);
        for i in 0..4 {
            let outer = if Some(i) == active_idx { cyan } else { muted };
            self.rail_icons[i].layout(flatland, ix, iy, icon, icon, outer)?;
            let core = icon.saturating_sub(12).max(8);
            self.rail_icon_cores[i].layout(
                flatland,
                ix + (icon - core) / 2,
                iy + (icon - core) / 2,
                core,
                core,
                if Some(i) == active_idx { violet } else { panel },
            )?;
            iy += icon + gap;
        }

        // Inspector region + cards.
        self.inspector.layout(
            flatland,
            inspector.x,
            inspector.y,
            inspector.width,
            inspector.height,
            panel,
        )?;
        self.inspector_accent.layout(
            flatland,
            inspector.x,
            inspector.y,
            inspector.width,
            3,
            cyan,
        )?;

        let card_count = 4u32;
        let pad = 10u32;
        let usable_w = inspector.width.saturating_sub(pad * 2);
        let card_w = usable_w.saturating_sub(pad * (card_count - 1)) / card_count;
        let card_h = inspector.height.saturating_sub(pad * 2 + 6).max(24);
        let card_y = inspector.y + pad + 4;
        let fills = [
            meter_color(state.tile_count.min(4) as f32 / 4.0, cyan, muted),
            if !state.confirmed_focus.is_empty() { cyan } else { muted },
            meter_color((state.gap_px as f32 / 24.0).clamp(0.15, 1.0), violet, muted),
            meter_color((state.present_count.min(12) as f32) / 12.0, ok, muted),
        ];
        for i in 0..4 {
            let cx = inspector.x + pad + i as u32 * (card_w + pad);
            self.inspector_cards[i].layout(flatland, cx, card_y, card_w, card_h, panel_bg)?;
            let bar_h = 8u32;
            self.inspector_card_bars[i].layout(
                flatland,
                cx + 8,
                card_y + card_h.saturating_sub(bar_h + 8),
                card_w.saturating_sub(16).max(1),
                bar_h,
                fills[i],
            )?;
        }
        Ok(())
    }
}

fn active_rail_index(state: &ChromeState) -> Option<usize> {
    let focus = state.confirmed_focus.to_ascii_lowercase();
    if focus.is_empty() {
        return None;
    }
    // Order of marks: browser, terminal, files, settings
    let names = ["browser", "terminal", "files", "settings"];
    for (idx, name) in names.iter().enumerate() {
        if focus.contains(name) {
            return Some(idx);
        }
    }
    // Fall back to first order entry family.
    if let Some(first) = state.order.first() {
        let f = first.to_ascii_lowercase();
        for (idx, name) in names.iter().enumerate() {
            if f.contains(name) {
                return Some(idx);
            }
        }
    }
    None
}

fn meter_color(t: f32, hot: ui_comp::ColorRgba, cold: ui_comp::ColorRgba) -> ui_comp::ColorRgba {
    let t = t.clamp(0.0, 1.0);
    rgba(
        cold.red + (hot.red - cold.red) * t,
        cold.green + (hot.green - cold.green) * t,
        cold.blue + (hot.blue - cold.blue) * t,
        1.0,
    )
}
