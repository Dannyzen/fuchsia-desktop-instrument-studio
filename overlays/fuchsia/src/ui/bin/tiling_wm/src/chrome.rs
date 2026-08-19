// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Instrument Studio chrome: multi-rect iconography + 5x7 bitmap labels.

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

const GLYPH_PARTS: usize = 64;
const RAIL_SLOTS: usize = 6;
const PARTS_PER_ICON: usize = 8;
const LABEL_PARTS: usize = 360;

fn glyph5(ch: u8) -> [u8; 7] {
    match ch {
        b' ' => [0, 0, 0, 0, 0, 0, 0],
        b'-' => [0, 0, 0, 31, 0, 0, 0],
        b'.' => [0, 0, 0, 0, 0, 4, 4],
        b'/' => [1, 2, 2, 4, 8, 8, 16],
        b'0' => [14, 17, 19, 21, 25, 17, 14],
        b'1' => [4, 12, 4, 4, 4, 4, 14],
        b'2' => [14, 17, 1, 2, 4, 8, 31],
        b'3' => [30, 1, 1, 14, 1, 1, 30],
        b'4' => [2, 6, 10, 18, 31, 2, 2],
        b'5' => [31, 16, 30, 1, 1, 17, 14],
        b'6' => [6, 8, 16, 30, 17, 17, 14],
        b'7' => [31, 1, 2, 4, 8, 8, 8],
        b'8' => [14, 17, 17, 14, 17, 17, 14],
        b'9' => [14, 17, 17, 15, 1, 2, 12],
        b':' => [0, 4, 4, 0, 4, 4, 0],
        b'A' => [14, 17, 17, 31, 17, 17, 17],
        b'B' => [30, 17, 17, 30, 17, 17, 30],
        b'C' => [14, 17, 16, 16, 16, 17, 14],
        b'D' => [30, 17, 17, 17, 17, 17, 30],
        b'E' => [31, 16, 16, 30, 16, 16, 31],
        b'F' => [31, 16, 16, 30, 16, 16, 16],
        b'G' => [14, 17, 16, 23, 17, 17, 14],
        b'H' => [17, 17, 17, 31, 17, 17, 17],
        b'I' => [14, 4, 4, 4, 4, 4, 14],
        b'J' => [7, 2, 2, 2, 2, 18, 12],
        b'K' => [17, 18, 20, 24, 20, 18, 17],
        b'L' => [16, 16, 16, 16, 16, 16, 31],
        b'M' => [17, 27, 21, 17, 17, 17, 17],
        b'N' => [17, 25, 21, 19, 17, 17, 17],
        b'O' => [14, 17, 17, 17, 17, 17, 14],
        b'P' => [30, 17, 17, 30, 16, 16, 16],
        b'Q' => [14, 17, 17, 17, 21, 18, 13],
        b'R' => [30, 17, 17, 30, 20, 18, 17],
        b'S' => [15, 16, 16, 14, 1, 1, 30],
        b'T' => [31, 4, 4, 4, 4, 4, 4],
        b'U' => [17, 17, 17, 17, 17, 17, 14],
        b'V' => [17, 17, 17, 17, 17, 10, 4],
        b'W' => [17, 17, 17, 21, 21, 21, 10],
        b'X' => [17, 17, 10, 4, 10, 17, 17],
        b'Y' => [17, 17, 10, 4, 4, 4, 4],
        b'Z' => [31, 1, 2, 4, 8, 16, 31],
        _ => [0, 0, 0, 0b01110, 0, 0, 0],
    }
}

/// Draw ASCII uppercase labels using 5x7 bitmaps packed into horizontal runs.
/// Run-length bars keep label parts bounded when glyph scale is 3-4px.
fn draw_text(
    parts: &[Bar],
    flatland: &ui_comp::FlatlandProxy,
    mut cursor: usize,
    x: i32,
    y: i32,
    text: &str,
    px: u32,
    color: ui_comp::ColorRgba,
) -> Result<usize, Error> {
    let mut cx = x;
    let gap = px.max(1);
    for ch in text.bytes() {
        let rows = glyph5(ch.to_ascii_uppercase());
        for (ry, row) in rows.iter().enumerate() {
            let mut rx = 0u32;
            while rx < 5 {
                if (row >> (4 - rx)) & 1 == 0 {
                    rx += 1;
                    continue;
                }
                let start = rx;
                while rx < 5 && (row >> (4 - rx)) & 1 == 1 {
                    rx += 1;
                }
                if cursor >= parts.len() {
                    return Ok(cursor);
                }
                parts[cursor].layout(
                    flatland,
                    cx + (start as i32) * px as i32,
                    y + (ry as i32) * px as i32,
                    (rx - start) * px,
                    px,
                    color,
                )?;
                cursor += 1;
            }
        }
        cx += (5 * px as i32) + gap as i32;
    }
    Ok(cursor)
}

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
    labels: [Bar; LABEL_PARTS],
}

impl ShellChrome {
    pub fn create(
        flatland: &ui_comp::FlatlandProxy,
        ids: &mut IdGenerator,
        root: &ui_comp::TransformId,
    ) -> Result<Self, Error> {
        let mk = |flatland: &ui_comp::FlatlandProxy, ids: &mut IdGenerator| Bar::create(flatland, ids, root);
        let mut labels = Vec::with_capacity(LABEL_PARTS);
        for _ in 0..LABEL_PARTS {
            labels.push(mk(flatland, ids)?);
        }
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
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
            ],
            rail_parts: {
                let mut v = Vec::with_capacity(GLYPH_PARTS);
                for _ in 0..GLYPH_PARTS {
                    v.push(mk(flatland, ids)?);
                }
                v.try_into().map_err(|_| anyhow!("rail_parts len"))?
            },
            inspector: mk(flatland, ids)?,
            inspector_accent: mk(flatland, ids)?,
            inspector_cards: [
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
            ],
            inspector_card_bars: [
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
            ],
            inspector_card_icons: [
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
                mk(flatland, ids)?,
            ],
            labels: labels.try_into().map_err(|_| anyhow!("labels len"))?,
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
        let muted = rgba(0.20, 0.23, 0.28, 1.0);
        let faint = rgba(0.42, 0.48, 0.55, 1.0);
        let text = rgba(0.96, 0.97, 0.98, 1.0);
        let cyan = rgba(0.0, 0.918, 1.0, 1.0);
        let violet = rgba(0.545, 0.486, 1.0, 1.0);
        let green = rgba(0.239, 0.839, 0.549, 1.0);
        let cyan_dim = rgba(0.0, 0.918, 1.0, 0.22);
        let line = rgba(1.0, 1.0, 1.0, 0.08);
        let elev = rgba(0.082, 0.106, 0.141, 1.0);
        let rail_bg = rgba(0.039, 0.055, 0.078, 1.0);

        for p in &self.labels {
            p.hide(flatland)?;
        }
        for p in &self.rail_parts {
            p.hide(flatland)?;
        }
        for p in &self.inspector_card_icons {
            p.hide(flatland)?;
        }

        self.strip.layout(flatland, strip.x as i32, strip.y as i32, strip.width, strip.height, panel)?;
        self.strip_accent.layout(
            flatland,
            strip.x as i32,
            (strip.y + strip.height.saturating_sub(2)) as i32,
            strip.width,
            2,
            cyan,
        )?;

        let mark = strip.height.saturating_sub(12).clamp(22, 30);
        let bx = (strip.x + 12) as i32;
        let by = (strip.y + (strip.height - mark) / 2) as i32;
        self.brand_a.layout(flatland, bx, by, mark / 2, mark, cyan)?;
        self.brand_b.layout(flatland, bx + (mark / 2) as i32, by, mark - mark / 2, mark, violet)?;

        let mut li = 0usize;
        let brand_px = 3u32;
        let brand_text = if strip.width < 820 { "STUDIO" } else { "WORKBENCH STUDIO" };
        li = draw_text(
            &self.labels,
            flatland,
            li,
            bx + mark as i32 + 10,
            by + (mark as i32 - 7 * brand_px as i32) / 2,
            brand_text,
            brand_px,
            text,
        )?;

        let pill_h = strip.height.saturating_sub(14).max(18);
        let pill_w = if strip.width < 800 { 72 } else { 92 };
        let brand_w = if strip.width < 820 { 5 * 6 * 3 + 24 } else { 15 * 6 * 3 + 24 };
        let mut px = bx + mark as i32 + brand_w;
        let py = (strip.y + (strip.height - pill_h) / 2) as i32;
        let pill_labels = ["BUILD", "RSRCH", "OPS"];
        for i in 0..3 {
            let active = i == 0;
            let fill = if active { cyan_dim } else { elev };
            self.pills[i].layout(flatland, px, py, pill_w, pill_h, fill)?;
            self.pill_accents[i].layout(
                flatland,
                px,
                py + pill_h as i32 - 2,
                pill_w,
                2,
                if active { cyan } else { line },
            )?;
            let tpx = 3u32;
            let tw = (pill_labels[i].len() as i32) * (5 * tpx as i32 + tpx as i32);
            li = draw_text(
                &self.labels,
                flatland,
                li,
                px + (pill_w as i32 - tw) / 2,
                py + (pill_h as i32 - 7 * tpx as i32) / 2,
                pill_labels[i],
                tpx,
                if active { cyan } else { faint },
            )?;
            px += pill_w as i32 + 8;
        }

        let chip_w = if strip.width < 800 { 62 } else { 74 };
        let chip_h = pill_h;
        let mut cx = (strip.x + strip.width) as i32 - 12;
        let chips = [
            (state.tile_count > 0, green, "OK"),
            (!state.confirmed_focus.is_empty(), cyan, "FOC"),
            (state.gap_px > 0, violet, "GAP"),
        ];
        for i in (0..3).rev() {
            cx -= chip_w as i32;
            self.status_chips[i].layout(flatland, cx, py, chip_w, chip_h, elev)?;
            let d = 8u32;
            self.status_dots[i].layout(
                flatland,
                cx + 6,
                py + (chip_h as i32 - d as i32) / 2,
                d,
                d,
                if chips[i].0 { chips[i].1 } else { faint },
            )?;
            li = draw_text(
                &self.labels,
                flatland,
                li,
                cx + 18,
                py + (chip_h as i32 - 21) / 2,
                chips[i].2,
                3,
                if chips[i].0 { text } else { faint },
            )?;
            cx -= 8;
        }

        self.rail.layout(flatland, rail.x as i32, rail.y as i32, rail.width, rail.height, rail_bg)?;
        self.rail_edge.layout(
            flatland,
            (rail.x + rail.width.saturating_sub(1)) as i32,
            rail.y as i32,
            1,
            rail.height,
            line,
        )?;

        let slot = rail.width.saturating_sub(14).clamp(34, 42);
        let gap = 8u32;
        let mut iy = (rail.y + 14) as i32;
        let ix = (rail.x + (rail.width - slot) / 2) as i32;
        let active = active_rail_index(state);
        let highlight = match active {
            Some(0) => 3,
            Some(1) => 4,
            Some(2) => 2,
            Some(3) => 5,
            Some(_) | None => 0,
        };
        for i in 0..RAIL_SLOTS {
            let is_active = i == highlight;
            let slot_bg = if is_active {
                rgba(1.0, 1.0, 1.0, 0.05)
            } else {
                rgba(0.0, 0.0, 0.0, 0.0)
            };
            let slot_border = if is_active {
                rgba(0.0, 0.918, 1.0, 0.35)
            } else {
                rgba(0.0, 0.0, 0.0, 0.0)
            };
            self.rail_slots[i].layout(flatland, ix, iy, slot, slot, slot_bg)?;
            let base = i * PARTS_PER_ICON;
            let ink = if is_active { cyan } else { faint };
            if is_active {
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
                )?;
            } else {
                draw_rail_glyph(&self.rail_parts[base..base + 4], flatland, ix, iy, slot, i, ink)?;
                for p in &self.rail_parts[base + 4..base + PARTS_PER_ICON] {
                    p.hide(flatland)?;
                }
            }
            iy += (slot + gap) as i32;
        }

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
        li = draw_text(
            &self.labels,
            flatland,
            li,
            inspector.x as i32 + 10,
            inspector.y as i32 + 6,
            "INSPECT",
            3,
            cyan,
        )?;

        let pad = 10u32;
        let card_count = 4u32;
        let usable = inspector.width.saturating_sub(pad * 2);
        let card_w = usable.saturating_sub(pad * (card_count - 1)) / card_count;
        let card_h = inspector.height.saturating_sub(pad * 2 + 14).max(28);
        let card_y = (inspector.y + pad + 12) as i32;
        let fills = [
            meter_color(state.tile_count.min(4) as f32 / 4.0, cyan, muted),
            if !state.confirmed_focus.is_empty() { cyan } else { muted },
            meter_color((state.gap_px as f32 / 24.0).clamp(0.15, 1.0), violet, muted),
            meter_color((state.present_count.min(12) as f32) / 12.0, green, muted),
        ];
        let card_labels = ["TILES", "FOCUS", "GAP", "LIVE"];
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
            let ip = &self.inspector_card_icons[i * 2..i * 2 + 2];
            draw_inspector_mini_icon(ip, flatland, x + 8, card_y + 8, i, fills[i], faint)?;
            li = draw_text(
                &self.labels,
                flatland,
                li,
                x + 24,
                card_y + 8,
                card_labels[i],
                3,
                text,
            )?;
        }
        let _ = li;
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
) -> Result<(), Error> {
    let g = slot.saturating_sub(16).clamp(16, 22);
    let gx = slot_x + ((slot - g) / 2) as i32;
    let gy = slot_y + ((slot - g) / 2) as i32;
    for p in parts {
        p.hide(flatland)?;
    }
    match kind {
        0 => {
            if parts.len() >= 3 {
                let t = (g / 5).max(2);
                parts[0].layout(flatland, gx + (g as i32 - t as i32) / 2, gy + 2, t, g - 4, ink)?;
                parts[1].layout(flatland, gx + 2, gy + (g as i32 - t as i32) / 2, g - 4, t, ink)?;
                let k = (g / 3).max(3);
                parts[2].layout(
                    flatland,
                    gx + (g as i32 - k as i32) / 2,
                    gy + (g as i32 - k as i32) / 2,
                    k,
                    k,
                    ink,
                )?;
            }
        }
        1 => {
            if parts.len() >= 4 {
                let cell = (g / 2).saturating_sub(2).max(4);
                let gap = 2i32;
                parts[0].layout(flatland, gx, gy, cell, cell, ink)?;
                parts[1].layout(flatland, gx + cell as i32 + gap, gy, cell, cell, ink)?;
                parts[2].layout(flatland, gx, gy + cell as i32 + gap, cell, cell, ink)?;
                parts[3].layout(
                    flatland,
                    gx + cell as i32 + gap,
                    gy + cell as i32 + gap,
                    cell,
                    cell,
                    ink,
                )?;
            }
        }
        2 => {
            if parts.len() >= 4 {
                parts[0].layout(flatland, gx + 3, gy + 1, g - 6, g - 2, ink)?;
                let f = (g / 3).max(4);
                parts[1].layout(
                    flatland,
                    gx + g as i32 - 3 - f as i32,
                    gy + 1,
                    f,
                    f,
                    rgba(0.039, 0.055, 0.078, 1.0),
                )?;
                let lw = g - 12;
                parts[2].layout(
                    flatland,
                    gx + 6,
                    gy + g as i32 / 2,
                    lw,
                    2,
                    rgba(0.039, 0.055, 0.078, 1.0),
                )?;
                parts[3].layout(
                    flatland,
                    gx + 6,
                    gy + g as i32 / 2 + 4,
                    lw.saturating_sub(3),
                    2,
                    rgba(0.039, 0.055, 0.078, 1.0),
                )?;
            }
        }
        3 => {
            if parts.len() >= 4 {
                parts[0].layout(flatland, gx, gy, g, 2, ink)?;
                parts[1].layout(flatland, gx, gy + g as i32 - 2, g, 2, ink)?;
                parts[2].layout(flatland, gx, gy, 2, g, ink)?;
                parts[3].layout(flatland, gx + g as i32 - 2, gy, 2, g, ink)?;
            }
        }
        4 => {
            if parts.len() >= 4 {
                let t = 3u32;
                parts[0].layout(flatland, gx + 3, gy + 4, t, t, ink)?;
                parts[1].layout(flatland, gx + 6, gy + (g as i32 / 2) - 1, t + 1, t, ink)?;
                parts[2].layout(flatland, gx + 3, gy + g as i32 - 7, t, t, ink)?;
                parts[3].layout(flatland, gx + g as i32 / 2, gy + g as i32 - 6, g / 2 - 2, 3, ink)?;
            }
        }
        _ => {
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
                parts[2].layout(
                    flatland,
                    gx + (g as i32 - n as i32) / 2,
                    gy + g as i32 - n as i32 - 1,
                    n,
                    n + 1,
                    ink,
                )?;
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
            if parts.len() >= 2 {
                parts[0].layout(flatland, x, y, 5, 5, hot)?;
                parts[1].layout(flatland, x + 7, y + 7, 5, 5, cold)?;
            }
        }
        1 => {
            if parts.len() >= 2 {
                parts[0].layout(flatland, x, y, 12, 12, hot)?;
                parts[1].layout(flatland, x + 3, y + 3, 6, 6, rgba(0.082, 0.106, 0.141, 1.0))?;
            }
        }
        2 => {
            if parts.len() >= 2 {
                parts[0].layout(flatland, x, y + 2, 12, 3, hot)?;
                parts[1].layout(flatland, x, y + 8, 12, 3, cold)?;
            }
        }
        _ => {
            if parts.len() >= 2 {
                parts[0].layout(flatland, x + 3, y + 3, 6, 6, hot)?;
                parts[1].layout(flatland, x + 5, y + 5, 2, 2, rgba(0.07, 0.09, 0.12, 1.0))?;
            }
        }
    }
    Ok(())
}

fn active_rail_index(state: &ChromeState) -> Option<usize> {
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
