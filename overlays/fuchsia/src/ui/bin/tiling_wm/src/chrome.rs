// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Instrument Studio chrome with production-closer multi-rect iconography.
//!
//! Rail order matches design/sketches/01-instrument-studio:
//! Launcher, Overview, Files, Browser, Terminal, Settings (+ status marks).

use anyhow::{anyhow, Context, Error};
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
        x: i32,
        y: i32,
        width: u32,
        height: u32,
        color: ui_comp::ColorRgba,
    ) -> Result<(), Error> {
        let width = width.max(1);
        let height = height.max(1);
        // Park unused pieces offscreen with 1x1 muted fill.
        flatland
            .set_solid_fill(&self.content, &color, &fmath::SizeU { width, height })
            .context("chrome solid fill")?;
        flatland
            .set_translation(&self.transform, &fmath::Vec_ { x, y })
            .context("chrome translate")?;
        Ok(())
    }

    fn hide(&self, flatland: &ui_comp::FlatlandProxy) -> Result<(), Error> {
        self.layout(flatland, -64, -64, 1, 1, rgba(0.0, 0.0, 0.0, 0.0))
    }
}

fn rgba(r: f32, g: f32, b: f32, a: f32) -> ui_comp::ColorRgba {
    ui_comp::ColorRgba { red: r, green: g, blue: b, alpha: a }
}

/// Pool of rect primitives used to compose multi-part glyphs.
const GLYPH_PARTS: usize = 64;
const RAIL_SLOTS: usize = 6;
const PARTS_PER_ICON: usize = 8;

pub struct ShellChrome {
    strip: Bar,
    strip_accent: Bar,
    brand_a: Bar,
    brand_b: Bar,
    pills: [Bar; 3],
    pill_accents: [Bar; 3],
    status_chips: [Bar; 3],
    status_dots: [Bar; 3],
    rail: Bar,
    rail_edge: Bar,
    rail_slots: [Bar; RAIL_SLOTS],
    rail_parts: [Bar; GLYPH_PARTS],
    inspector: Bar,
    inspector_accent: Bar,
    inspector_cards: [Bar; 4],
    inspector_card_bars: [Bar; 4],
    inspector_card_icons: [Bar; 8],
}

impl ShellChrome {
    pub fn create(
        flatland: &ui_comp::FlatlandProxy,
        ids: &mut IdGenerator,
        root: &ui_comp::TransformId,
    ) -> Result<Self, Error> {
        let mk = |flatland: &ui_comp::FlatlandProxy, ids: &mut IdGenerator| Bar::create(flatland, ids, root);
        Ok(Self {
            strip: mk(flatland, ids)?,
            strip_accent: mk(flatland, ids)?,
            brand_a: mk(flatland, ids)?,
            brand_b: mk(flatland, ids)?,
            pills: [mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?],
            pill_accents: [mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?],
            status_chips: [mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?],
            status_dots: [mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?],
            rail: mk(flatland, ids)?,
            rail_edge: mk(flatland, ids)?,
            rail_slots: [
                mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?,
                mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?,
            ],
            rail_parts: {
                // 64 glyph parts
                let mut v = Vec::with_capacity(64);
                for _ in 0..64 { v.push(mk(flatland, ids)?); }
                v.try_into().map_err(|_| anyhow::anyhow!("rail_parts len"))?
            },
            inspector: mk(flatland, ids)?,
            inspector_accent: mk(flatland, ids)?,
            inspector_cards: [mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?],
            inspector_card_bars: [mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?],
            inspector_card_icons: [
                mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?,
                mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?,
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
            1.0,
        );
        let panel_bg = rgba(theme.panel_bg.red, theme.panel_bg.green, theme.panel_bg.blue, 1.0);
        let muted = rgba(0.20, 0.23, 0.28, 1.0);
        let faint = rgba(0.42, 0.48, 0.55, 1.0);
        let cyan = rgba(0.0, 0.918, 1.0, 1.0); // #00eaff
        let violet = rgba(0.545, 0.486, 1.0, 1.0); // #8b7cff
        let green = rgba(0.239, 0.839, 0.549, 1.0); // #3dd68c
        let cyan_dim = rgba(0.0, 0.918, 1.0, 0.22);
        let line = rgba(1.0, 1.0, 1.0, 0.08);
        let elev = rgba(0.082, 0.106, 0.141, 1.0); // #151b24-ish

        // Strip
        self.strip.layout(flatland, strip.x as i32, strip.y as i32, strip.width, strip.height, panel)?;
        self.strip_accent.layout(
            flatland,
            strip.x as i32,
            (strip.y + strip.height.saturating_sub(2)) as i32,
            strip.width,
            2,
            cyan,
        )?;

        // Brand mark: rounded-square proxy with cyan→violet split (design .mark).
        let mark = strip.height.saturating_sub(12).clamp(22, 30);
        let bx = (strip.x + 12) as i32;
        let by = (strip.y + (strip.height - mark) / 2) as i32;
        self.brand_a.layout(flatland, bx, by, mark / 2, mark, cyan)?;
        self.brand_b.layout(flatland, bx + (mark / 2) as i32, by, mark - mark / 2, mark, violet)?;

        // Workspace pills: Build/Research/Ops
        let pill_h = strip.height.saturating_sub(14).max(18);
        let pill_w = if strip.width < 800 { 52 } else { 70 };
        let mut px = bx + mark as i32 + 14;
        let py = (strip.y + (strip.height - pill_h) / 2) as i32;
        for i in 0..3 {
            let active = i == 0;
            let fill = if active { cyan_dim } else { elev };
            self.pills[i].layout(flatland, px, py, pill_w, pill_h, fill)?;
            // top hairline / bottom active underline
            self.pill_accents[i].layout(
                flatland,
                px,
                py + pill_h as i32 - 2,
                pill_w,
                2,
                if active { cyan } else { line },
            )?;
            px += pill_w as i32 + 8;
        }

        // Status chips right: healthy / focus / gaps
        let chip_w = if strip.width < 800 { 46 } else { 58 };
        let chip_h = pill_h;
        let mut cx = (strip.x + strip.width) as i32 - 12;
        let chips = [
            (state.tile_count > 0, green),
            (!state.confirmed_focus.is_empty(), cyan),
            (state.gap_px > 0, violet),
        ];
        for i in (0..3).rev() {
            cx -= chip_w as i32;
            self.status_chips[i].layout(flatland, cx, py, chip_w, chip_h, elev)?;
            let d = 8u32;
            self.status_dots[i].layout(
                flatland,
                cx + 8,
                py + (chip_h as i32 - d as i32) / 2,
                d,
                d,
                if chips[i].0 { chips[i].1 } else { faint },
            )?;
            cx -= 8;
        }

        // Rail background + right line
        self.rail.layout(flatland, rail.x as i32, rail.y as i32, rail.width, rail.height, rgba(0.039, 0.055, 0.078, 1.0))?;
        self.rail_edge.layout(
            flatland,
            (rail.x + rail.width.saturating_sub(1)) as i32,
            rail.y as i32,
            1,
            rail.height,
            line,
        )?;

        // Hide all glyph parts first.
        for p in &self.rail_parts {
            p.hide(flatland)?;
        }
        for p in &self.inspector_card_icons {
            p.hide(flatland)?;
        }

        // Rail icons: launcher, overview, files, browser, terminal, settings
        let slot = rail.width.saturating_sub(14).clamp(34, 42);
        let gap = 8u32;
        let mut iy = (rail.y + 14) as i32;
        let ix = (rail.x + (rail.width - slot) / 2) as i32;
        let active = active_rail_index(state); // maps focus to browser/terminal/files/settings
        // Design order: 0 launcher, 1 overview, 2 files, 3 browser, 4 terminal, 5 settings
        // Highlight matching app slot; launcher is default shell active when none.
        let highlight = match active {
            Some(0) => 3, // browser
            Some(1) => 4, // terminal
            Some(2) => 2, // files
            Some(3) => 5, // settings
            Some(_) | None => 0,
        };

        for i in 0..RAIL_SLOTS {
            let is_active = i == highlight;
            let slot_bg = if is_active { rgba(1.0, 1.0, 1.0, 0.05) } else { rgba(0.0, 0.0, 0.0, 0.0) };
            let slot_border = if is_active { rgba(0.0, 0.918, 1.0, 0.35) } else { rgba(0.0, 0.0, 0.0, 0.0) };
            // base slot
            self.rail_slots[i].layout(flatland, ix, iy, slot, slot, if is_active { slot_bg } else { rgba(0.0, 0.0, 0.0, 0.0) })?;
            // active inset border as 4 thin rects using first parts of this icon group when active
            let base = i * PARTS_PER_ICON;
            let ink = if is_active { cyan } else { faint };
            if is_active {
                // top/bottom/left/right border 1px using parts 0-3 temporarily then glyph uses 0..
                // draw border with dedicated first 4 parts, glyph on remaining 4? Better: border via outer
                // Use slot itself for bg; draw 1px border with parts 0..3, glyph with 4..7
                self.rail_parts[base].layout(flatland, ix, iy, slot, 1, slot_border)?;
                self.rail_parts[base + 1].layout(flatland, ix, iy + slot as i32 - 1, slot, 1, slot_border)?;
                self.rail_parts[base + 2].layout(flatland, ix, iy, 1, slot, slot_border)?;
                self.rail_parts[base + 3].layout(flatland, ix + slot as i32 - 1, iy, 1, slot, slot_border)?;
                draw_rail_glyph(
                    &self.rail_parts[base + 4..base + PARTS_PER_ICON],
                    flatland,
                    ix,
                    iy,
                    slot,
                    i,
                    ink,
                    panel,
                )?;
            } else {
                draw_rail_glyph(
                    &self.rail_parts[base..base + 4],
                    flatland,
                    ix,
                    iy,
                    slot,
                    i,
                    ink,
                    panel,
                )?;
                // hide leftover parts in group
                for p in &self.rail_parts[base + 4..base + PARTS_PER_ICON] {
                    p.hide(flatland)?;
                }
            }
            iy += (slot + gap) as i32;
        }

        // Inspector
        self.inspector.layout(
            flatland,
            inspector.x as i32,
            inspector.y as i32,
            inspector.width,
            inspector.height,
            panel,
        )?;
        self.inspector_accent.layout(
            flatland,
            inspector.x as i32,
            inspector.y as i32,
            inspector.width,
            2,
            cyan,
        )?;

        let pad = 10u32;
        let card_count = 4u32;
        let usable = inspector.width.saturating_sub(pad * 2);
        let card_w = usable.saturating_sub(pad * (card_count - 1)) / card_count;
        let card_h = inspector.height.saturating_sub(pad * 2 + 4).max(28);
        let card_y = (inspector.y + pad + 2) as i32;
        let fills = [
            meter_color(state.tile_count.min(4) as f32 / 4.0, cyan, muted),
            if !state.confirmed_focus.is_empty() { cyan } else { muted },
            meter_color((state.gap_px as f32 / 24.0).clamp(0.15, 1.0), violet, muted),
            meter_color((state.present_count.min(12) as f32) / 12.0, green, muted),
        ];
        // icon kinds: tiles grid, focus ring, gap bars, heart/health
        for i in 0..4 {
            let x = (inspector.x + pad + i as u32 * (card_w + pad)) as i32;
            self.inspector_cards[i].layout(flatland, x, card_y, card_w, card_h, elev)?;
            let bar_h = 7u32;
            self.inspector_card_bars[i].layout(
                flatland,
                x + 8,
                card_y + card_h as i32 - bar_h as i32 - 8,
                card_w.saturating_sub(16).max(1),
                bar_h,
                fills[i],
            )?;
            // mini icon top-left of card (2 parts each)
            let ip = &self.inspector_card_icons[i * 2..i * 2 + 2];
            draw_inspector_mini_icon(ip, flatland, x + 10, card_y + 8, i, fills[i], faint)?;
        }
        Ok(())
    }
}

fn draw_rail_glyph(
    parts: &[Bar],
    flatland: &ui_comp::FlatlandProxy,
    slot_x: i32,
    slot_y: i32,
    slot: u32,
    kind: usize,
    ink: ui_comp::ColorRgba,
    _panel: ui_comp::ColorRgba,
) -> Result<(), Error> {
    // Center a 18-22px glyph box inside slot.
    let g = slot.saturating_sub(16).clamp(16, 22);
    let gx = slot_x + ((slot - g) / 2) as i32;
    let gy = slot_y + ((slot - g) / 2) as i32;
    // Hide all provided parts first.
    for p in parts {
        p.hide(flatland)?;
    }
    match kind {
        0 => {
            // Launcher command-ish: plus with center diamond proxy (⌘ simplified as + in rounded field)
            // outer ring corners via 4 blocks + center
            if parts.len() >= 4 {
                let t = (g / 5).max(2);
                // vertical bar
                parts[0].layout(flatland, gx + (g as i32 - t as i32) / 2, gy + 2, t, g - 4, ink)?;
                // horizontal bar
                parts[1].layout(flatland, gx + 2, gy + (g as i32 - t as i32) / 2, g - 4, t, ink)?;
                // center knobs
                let k = (g / 3).max(3);
                parts[2].layout(flatland, gx + (g as i32 - k as i32) / 2, gy + (g as i32 - k as i32) / 2, k, k, ink)?;
            }
        }
        1 => {
            // Overview grid 2x2
            if parts.len() >= 4 {
                let cell = (g / 2).saturating_sub(2).max(4);
                let gap = 2i32;
                parts[0].layout(flatland, gx, gy, cell, cell, ink)?;
                parts[1].layout(flatland, gx + cell as i32 + gap, gy, cell, cell, ink)?;
                parts[2].layout(flatland, gx, gy + cell as i32 + gap, cell, cell, ink)?;
                parts[3].layout(flatland, gx + cell as i32 + gap, gy + cell as i32 + gap, cell, cell, ink)?;
            }
        }
        2 => {
            // Files: document rect + folded corner + lines
            if parts.len() >= 4 {
                parts[0].layout(flatland, gx + 3, gy + 1, g - 6, g - 2, ink)?;
                // fold
                let f = (g / 3).max(4);
                parts[1].layout(flatland, gx + g as i32 - 3 - f as i32, gy + 1, f, f, rgba(0.039, 0.055, 0.078, 1.0))?;
                // text lines
                let lw = g - 12;
                parts[2].layout(flatland, gx + 6, gy + g as i32 / 2, lw, 2, rgba(0.039, 0.055, 0.078, 1.0))?;
                parts[3].layout(flatland, gx + 6, gy + g as i32 / 2 + 4, lw.saturating_sub(3), 2, rgba(0.039, 0.055, 0.078, 1.0))?;
            }
        }
        3 => {
            // Browser: outer ring + inner core (◎)
            if parts.len() >= 4 {
                // outer frame
                parts[0].layout(flatland, gx, gy, g, 2, ink)?;
                parts[1].layout(flatland, gx, gy + g as i32 - 2, g, 2, ink)?;
                parts[2].layout(flatland, gx, gy, 2, g, ink)?;
                parts[3].layout(flatland, gx + g as i32 - 2, gy, 2, g, ink)?;
            }
            // if more parts available for inner, caller may not have them in inactive path
        }
        4 => {
            // Terminal: prompt chevron + underscore (>_)
            if parts.len() >= 4 {
                let t = 3u32;
                // >
                parts[0].layout(flatland, gx + 3, gy + 4, t, t, ink)?;
                parts[1].layout(flatland, gx + 6, gy + (g as i32 / 2) - 1, t + 1, t, ink)?;
                parts[2].layout(flatland, gx + 3, gy + g as i32 - 7, t, t, ink)?;
                // _
                parts[3].layout(flatland, gx + g as i32 / 2, gy + g as i32 - 6, g / 2 - 2, 3, ink)?;
            }
        }
        5 | _ => {
            // Settings gear proxy: center hub + 4 nubs
            if parts.len() >= 4 {
                let hub = (g / 2).max(6);
                parts[0].layout(
                    flatland,
                    gx + (g as i32 - hub as i32) / 2,
                    gy + (g as i32 - hub as i32) / 2,
                    hub,
                    hub,
                    ink,
                )?;
                let n = 3u32;
                parts[1].layout(flatland, gx + (g as i32 - n as i32) / 2, gy, n, n + 1, ink)?;
                parts[2].layout(flatland, gx + (g as i32 - n as i32) / 2, gy + g as i32 - n as i32 - 1, n, n + 1, ink)?;
                parts[3].layout(flatland, gx, gy + (g as i32 - n as i32) / 2, n + 1, n, ink)?;
            }
        }
    }
    Ok(())
}

fn draw_inspector_mini_icon(
    parts: &[Bar],
    flatland: &ui_comp::FlatlandProxy,
    x: i32,
    y: i32,
    kind: usize,
    hot: ui_comp::ColorRgba,
    cold: ui_comp::ColorRgba,
) -> Result<(), Error> {
    for p in parts {
        p.hide(flatland)?;
    }
    match kind {
        0 => {
            // 2x2 tiles
            if parts.len() >= 2 {
                parts[0].layout(flatland, x, y, 5, 5, hot)?;
                parts[1].layout(flatland, x + 7, y + 7, 5, 5, cold)?;
            }
        }
        1 => {
            // focus ring proxy
            if parts.len() >= 2 {
                parts[0].layout(flatland, x, y, 12, 12, hot)?;
                parts[1].layout(flatland, x + 3, y + 3, 6, 6, rgba(0.082, 0.106, 0.141, 1.0))?;
            }
        }
        2 => {
            // gap bars
            if parts.len() >= 2 {
                parts[0].layout(flatland, x, y + 2, 12, 3, hot)?;
                parts[1].layout(flatland, x, y + 8, 12, 3, cold)?;
            }
        }
        _ => {
            // health pulse
            if parts.len() >= 2 {
                parts[0].layout(flatland, x + 3, y + 3, 6, 6, hot)?;
                parts[1].layout(flatland, x + 5, y + 5, 2, 2, rgba(0.07, 0.09, 0.12, 1.0))?;
            }
        }
    }
    Ok(())
}

fn active_rail_index(state: &ChromeState) -> Option<usize> {
    // browser, terminal, files, settings
    let focus = state.confirmed_focus.to_ascii_lowercase();
    if focus.is_empty() {
        return None;
    }
    let names = ["browser", "terminal", "files", "settings"];
    for (idx, name) in names.iter().enumerate() {
        if focus.contains(name) {
            return Some(idx);
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
