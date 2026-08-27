// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Instrument Studio chrome: readable font labels + semantic Material icons.

use crate::chrome_text::{ChromeTextSurface, TextRun};

use anyhow::{Context, Error, anyhow};
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
    pub tile_titles: Vec<TileTitle>,
}

#[derive(Clone, Debug, Default)]
pub struct TileTitle {
    pub x: i32,
    pub y: i32,
    pub label: String,
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
        Self::create_on(flatland, ids, root)
    }

    fn create_on(
        flatland: &ui_comp::FlatlandProxy,
        ids: &mut IdGenerator,
        parent: &ui_comp::TransformId,
    ) -> Result<Self, Error> {
        let transform = ids.next_transform_id();
        let content = ids.next_content_id();
        flatland
            .create_transform(&transform)
            .context("chrome create transform")?;
        flatland
            .create_filled_rect(&content)
            .context("chrome create rect")?;
        flatland
            .set_content(&transform, &content)
            .context("chrome set content")?;
        flatland
            .add_child(parent, &transform)
            .context("chrome add child")?;
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
    ui_comp::ColorRgba {
        red: r,
        green: g,
        blue: b,
        alpha: a,
    }
}

const TILE_NAME_PARTS: usize = 128;

pub struct TileName {
    parts: [Bar; TILE_NAME_PARTS],
}

impl TileName {
    pub fn create(
        flatland: &ui_comp::FlatlandProxy,
        ids: &mut IdGenerator,
        parent: &ui_comp::TransformId,
    ) -> Result<Self, Error> {
        let mut parts = Vec::with_capacity(TILE_NAME_PARTS);
        for _ in 0..TILE_NAME_PARTS {
            parts.push(Bar::create_on(flatland, ids, parent)?);
        }
        Ok(Self {
            parts: parts.try_into().map_err(|_| anyhow!("tile name parts"))?,
        })
    }

    pub fn layout(
        &self,
        flatland: &ui_comp::FlatlandProxy,
        label: &str,
        title_h: u32,
    ) -> Result<(), Error> {
        for p in &self.parts {
            p.hide(flatland)?;
        }
        let px = 4u32;
        let text = rgba(0.96, 0.97, 0.98, 1.0);
        let y = (title_h as i32 - 7 * px as i32) / 2;
        let _ = draw_text(&self.parts, flatland, 0, 16, y.max(2), label, px, text)?;
        Ok(())
    }
}

const RAIL_SLOTS: usize = 6;
const TEXT_PRIMARY: [u8; 4] = [245, 247, 250, 255];
const TEXT_SECONDARY: [u8; 4] = [150, 164, 181, 255];
const CYAN_TEXT: [u8; 4] = [0, 224, 255, 255];
const VIOLET_TEXT: [u8; 4] = [139, 124, 255, 255];

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
        b'a'..=b'z' => glyph5(ch.to_ascii_uppercase()),
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
        let rows = glyph5(ch);
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
    inspector: Bar,
    inspector_accent: Bar,
    inspector_cards: [Bar; 4],
    inspector_card_bars: [Bar; 4],
    _top_text: ChromeTextSurface,
    _rail_icons: ChromeTextSurface,
    _inspector_text: ChromeTextSurface,
}

impl ShellChrome {
    pub async fn create(
        flatland: &ui_comp::FlatlandProxy,
        ids: &mut IdGenerator,
        root: &ui_comp::TransformId,
        shell: &InstrumentStudioLayout,
    ) -> Result<Self, Error> {
        let mk = |flatland: &ui_comp::FlatlandProxy, ids: &mut IdGenerator| {
            Bar::create(flatland, ids, root)
        };
        // Create chrome surfaces first, then labels last so Flatland paints
        // wordmarks above strip/pills/cards instead of under them.
        let strip = mk(flatland, ids)?;
        let strip_accent = mk(flatland, ids)?;
        let brand_a = mk(flatland, ids)?;
        let brand_b = mk(flatland, ids)?;
        let pills = [mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?];
        let pill_accents = [mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?];
        let status_chips = [mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?];
        let status_dots = [mk(flatland, ids)?, mk(flatland, ids)?, mk(flatland, ids)?];
        let rail = mk(flatland, ids)?;
        let rail_edge = mk(flatland, ids)?;
        let rail_slots = [
            mk(flatland, ids)?,
            mk(flatland, ids)?,
            mk(flatland, ids)?,
            mk(flatland, ids)?,
            mk(flatland, ids)?,
            mk(flatland, ids)?,
        ];
        let inspector = mk(flatland, ids)?;
        let inspector_accent = mk(flatland, ids)?;
        let inspector_cards = [
            mk(flatland, ids)?,
            mk(flatland, ids)?,
            mk(flatland, ids)?,
            mk(flatland, ids)?,
        ];
        let inspector_card_bars = [
            mk(flatland, ids)?,
            mk(flatland, ids)?,
            mk(flatland, ids)?,
            mk(flatland, ids)?,
        ];
        let strip_region = shell.region_rect(ChromeRegion::WorkspaceStrip);
        let top_runs = top_text_runs(shell);
        let top_text = ChromeTextSurface::new(
            flatland,
            ids,
            root,
            fmath::SizeU {
                width: strip_region.width,
                height: strip_region.height,
            },
            fmath::Vec_ {
                x: strip_region.x as i32,
                y: strip_region.y as i32,
            },
            &top_runs,
            "WorkbenchChromeTop",
        )
        .await?;
        let rail_region = shell.region_rect(ChromeRegion::LauncherRail);
        let rail_runs = rail_icon_runs(shell);
        let rail_icons = ChromeTextSurface::new(
            flatland,
            ids,
            root,
            fmath::SizeU {
                width: rail_region.width,
                height: rail_region.height,
            },
            fmath::Vec_ {
                x: rail_region.x as i32,
                y: rail_region.y as i32,
            },
            &rail_runs,
            "WorkbenchChromeRailIcons",
        )
        .await?;
        let inspector_region = shell.region_rect(ChromeRegion::Inspector);
        let inspector_runs = inspector_text_runs(shell);
        let inspector_text = ChromeTextSurface::new(
            flatland,
            ids,
            root,
            fmath::SizeU {
                width: inspector_region.width,
                height: inspector_region.height,
            },
            fmath::Vec_ {
                x: inspector_region.x as i32,
                y: inspector_region.y as i32,
            },
            &inspector_runs,
            "WorkbenchChromeInspector",
        )
        .await?;
        Ok(Self {
            strip,
            strip_accent,
            brand_a,
            brand_b,
            pills,
            pill_accents,
            status_chips,
            status_dots,
            rail,
            rail_edge,
            rail_slots,
            inspector,
            inspector_accent,
            inspector_cards,
            inspector_card_bars,
            _top_text: top_text,
            _rail_icons: rail_icons,
            _inspector_text: inspector_text,
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
        let cyan = rgba(0.0, 0.918, 1.0, 1.0);
        let violet = rgba(0.545, 0.486, 1.0, 1.0);
        let green = rgba(0.239, 0.839, 0.549, 1.0);
        let cyan_dim = rgba(0.0, 0.918, 1.0, 0.22);
        let line = rgba(1.0, 1.0, 1.0, 0.08);
        let elev = rgba(0.082, 0.106, 0.141, 1.0);
        let rail_bg = rgba(0.039, 0.055, 0.078, 1.0);

        self.strip.layout(
            flatland,
            strip.x as i32,
            strip.y as i32,
            strip.width,
            strip.height,
            panel,
        )?;
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
        self.brand_a
            .layout(flatland, bx, by, mark / 2, mark, cyan)?;
        self.brand_b.layout(
            flatland,
            bx + (mark / 2) as i32,
            by,
            mark - mark / 2,
            mark,
            violet,
        )?;

        // Geometry remains stateful; words are painted once by ChromeTextSurface.
        let pill_h = strip.height.saturating_sub(16).max(18);
        let pill_w = if strip.width < 800 { 56 } else { 108 };
        let brand_w = if strip.width < 800 { 176 } else { 230 };
        let mut px = bx + mark as i32 + brand_w;
        let py = (strip.y + (strip.height - pill_h) / 2) as i32;
        let chip_w = if strip.width < 800 { 52 } else { 72 };
        let chips_total = 3 * chip_w as i32 + 2 * 8 + 12;
        let chips_left = (strip.x + strip.width) as i32 - chips_total;
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
            px += pill_w as i32 + 8;
        }
        let chip_h = pill_h;
        let mut cx = (strip.x + strip.width) as i32 - 12;
        let chips = [
            (state.tile_count > 0, green),
            (!state.confirmed_focus.is_empty(), cyan),
            (state.gap_px > 0, violet),
        ];
        for i in (0..3).rev() {
            cx -= chip_w as i32;
            if cx < chips_left {
                cx = chips_left + i as i32 * (chip_w as i32 + 8);
            }
            self.status_chips[i].layout(flatland, cx, py, chip_w, chip_h, elev)?;
            let d = 7u32;
            self.status_dots[i].layout(
                flatland,
                cx + 5,
                py + (chip_h as i32 - d as i32) / 2,
                d,
                d,
                if chips[i].0 { chips[i].1 } else { faint },
            )?;
            cx -= 8;
        }
        self.rail.layout(
            flatland,
            rail.x as i32,
            rail.y as i32,
            rail.width,
            rail.height,
            rail_bg,
        )?;
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
            let slot_bg = if i == highlight {
                rgba(0.0, 0.918, 1.0, 0.16)
            } else {
                rgba(0.0, 0.0, 0.0, 0.0)
            };
            self.rail_slots[i].layout(flatland, ix, iy, slot, slot, slot_bg)?;
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
        let pad = 10u32;
        let card_count = 4u32;
        let usable = inspector.width.saturating_sub(pad * 2);
        let card_w = usable.saturating_sub(pad * (card_count - 1)) / card_count;
        let card_h = inspector.height.saturating_sub(pad * 2 + 14).max(28);
        let card_y = (inspector.y + pad + 12) as i32;
        let fills = [
            meter_color(state.tile_count.min(4) as f32 / 4.0, cyan, muted),
            if !state.confirmed_focus.is_empty() {
                cyan
            } else {
                muted
            },
            meter_color((state.gap_px as f32 / 24.0).clamp(0.15, 1.0), violet, muted),
            meter_color((state.present_count.min(12) as f32) / 12.0, green, muted),
        ];
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
        }
        // Tile names are drawn on each tile header (TileName), not the chrome pool.
        Ok(())
    }
}

fn top_text_runs(shell: &InstrumentStudioLayout) -> Vec<TextRun<'static>> {
    let strip = shell.region_rect(ChromeRegion::WorkspaceStrip);
    let mark = strip.height.saturating_sub(12).clamp(22, 30);
    let bx = strip.x as i32 + 12;
    let by = (strip.y + (strip.height - mark) / 2) as i32;
    let narrow = strip.width < 800;
    let menu_font = if narrow { 12.0 } else { 14.0 };
    let pill_h = strip.height.saturating_sub(16).max(18);
    let pill_w = if narrow { 56 } else { 108 };
    let brand_w = if narrow { 176 } else { 230 };
    let mut pill_x = bx + mark as i32 + brand_w;
    let pill_y = ((strip.height - pill_h) / 2) as i32;
    let chip_w = if narrow { 52 } else { 72 };
    let chips_left = strip.width as i32 - (3 * chip_w as i32 + 2 * 8 + 12);
    let mut runs = vec![TextRun::text(
        "Workbench Studio",
        bx + mark as i32 + 10,
        by + (mark as i32 - menu_font as i32) / 2 - 2,
        menu_font,
        TEXT_PRIMARY,
    )];
    for (index, label) in ["Build", "Research", "Ops"].iter().enumerate() {
        let estimated_width = label.len() as i32 * if narrow { 7 } else { 8 };
        runs.push(TextRun::text(
            label,
            pill_x + (pill_w as i32 - estimated_width).max(4) / 2,
            pill_y + (pill_h as i32 - menu_font as i32) / 2 - 2,
            menu_font,
            if index == 0 {
                CYAN_TEXT
            } else {
                TEXT_SECONDARY
            },
        ));
        pill_x += pill_w as i32 + 8;
    }
    let status_font = if narrow { 10.0 } else { 12.0 };
    let mut chip_x = strip.width as i32 - 12;
    let labels = ["Ready", "Focus", "Gaps"];
    for index in (0..3).rev() {
        chip_x -= chip_w as i32;
        if chip_x < chips_left {
            chip_x = chips_left + index as i32 * (chip_w as i32 + 8);
        }
        runs.push(TextRun::text(
            labels[index],
            chip_x + 16,
            pill_y + (pill_h as i32 - status_font as i32) / 2 - 1,
            status_font,
            TEXT_PRIMARY,
        ));
        chip_x -= 8;
    }
    runs
}
fn rail_icon_runs(shell: &InstrumentStudioLayout) -> Vec<TextRun<'static>> {
    let rail = shell.region_rect(ChromeRegion::LauncherRail);
    let slot = rail.width.saturating_sub(14).clamp(34, 42);
    let gap = 8u32;
    let icon_size = 24.0;
    let icon_x = ((rail.width.saturating_sub(icon_size as u32)) / 2) as i32;
    let icons = [
        "\u{e145}", "\u{e871}", "\u{e2c7}", "\u{e80b}", "\u{e86f}", "\u{e8b8}",
    ];
    icons
        .iter()
        .enumerate()
        .map(|(index, icon)| {
            let slot_y = 14 + index as i32 * (slot + gap) as i32;
            TextRun::icon(
                icon,
                icon_x,
                slot_y + (slot as i32 - icon_size as i32) / 2 - 2,
                icon_size,
                TEXT_SECONDARY,
            )
        })
        .collect()
}
fn inspector_text_runs(shell: &InstrumentStudioLayout) -> Vec<TextRun<'static>> {
    let inspector = shell.region_rect(ChromeRegion::Inspector);
    let pad = 10u32;
    let card_w = inspector
        .width
        .saturating_sub(pad * 2)
        .saturating_sub(pad * 3)
        / 4;
    let card_y = pad as i32 + 12;
    let labels = [
        ("\u{e871}", "Tiles"),
        ("\u{e8b6}", "Focus"),
        ("\u{e86f}", "Gap"),
        ("\u{e80b}", "Live"),
    ];
    let mut runs = vec![TextRun::text("Inspect", 10, 6, 14.0, CYAN_TEXT)];
    for (index, (icon, label)) in labels.iter().enumerate() {
        let x = (pad + index as u32 * (card_w + pad)) as i32;
        runs.push(TextRun::icon(icon, x + 8, card_y + 6, 16.0, VIOLET_TEXT));
        runs.push(TextRun::text(label, x + 30, card_y + 8, 12.0, TEXT_PRIMARY));
    }
    runs
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
