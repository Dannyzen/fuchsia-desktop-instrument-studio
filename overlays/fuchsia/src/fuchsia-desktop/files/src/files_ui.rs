// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

pub const TOOLBAR_TOP: f32 = 88.0;
pub const TOOLBAR_BOTTOM: f32 = 136.0;
pub const LIST_TOP: f32 = 160.0;
pub const ROW_HEIGHT: f32 = 64.0;
pub const MAX_VISIBLE_ROWS: usize = 4;
pub const GRID_COLS: usize = 2;
pub const GRID_ROWS: usize = 2;
pub const GRID_TOP: f32 = 200.0;
pub const GRID_GAP: f32 = 8.0;
pub const GRID_PAD: f32 = 10.0;
pub const CELL_H: f32 = 88.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UiAction {
    Up,
    Open,
    Create,
    Rename,
    Copy,
    Move,
    Delete,
    Select(usize),
}

pub fn action_for_point(x: f32, y: f32) -> Option<UiAction> {
    action_for_point_in(x, y, 720.0)
}

pub fn grid_cell_width(width: f32) -> f32 {
    ((width - GRID_PAD * 2.0 - GRID_GAP) / GRID_COLS as f32).max(72.0)
}

pub fn action_for_point_in(x: f32, y: f32, width: f32) -> Option<UiAction> {
    if width < 520.0 {
        if (88.0..136.0).contains(&y) {
            return [
                (8.0..80.0, UiAction::Up),
                (84.0..156.0, UiAction::Open),
                (160.0..232.0, UiAction::Create),
                (236.0..316.0, UiAction::Rename),
            ]
            .into_iter()
            .find_map(|(range, action)| range.contains(&x).then_some(action));
        }
        if (140.0..188.0).contains(&y) {
            return [
                (8.0..80.0, UiAction::Copy),
                (84.0..156.0, UiAction::Move),
                (160.0..240.0, UiAction::Delete),
            ]
            .into_iter()
            .find_map(|(range, action)| range.contains(&x).then_some(action));
        }
        let cell_w = grid_cell_width(width);
        if y < GRID_TOP {
            return None;
        }
        let col = ((x - GRID_PAD) / (cell_w + GRID_GAP)).floor() as i32;
        let row = ((y - GRID_TOP) / (CELL_H + GRID_GAP)).floor() as i32;
        if col < 0 || row < 0 || col >= GRID_COLS as i32 || row >= GRID_ROWS as i32 {
            return None;
        }
        let local_x = x - GRID_PAD - col as f32 * (cell_w + GRID_GAP);
        let local_y = y - GRID_TOP - row as f32 * (CELL_H + GRID_GAP);
        if local_x < 0.0 || local_x >= cell_w || local_y < 0.0 || local_y >= CELL_H {
            return None;
        }
        let index = row as usize * GRID_COLS + col as usize;
        return (index < MAX_VISIBLE_ROWS).then_some(UiAction::Select(index));
    }
    if (TOOLBAR_TOP..TOOLBAR_BOTTOM).contains(&y) {
        return [
            (16.0..88.0, UiAction::Up),
            (96.0..168.0, UiAction::Open),
            (176.0..248.0, UiAction::Create),
            (256.0..344.0, UiAction::Rename),
            (352.0..424.0, UiAction::Copy),
            (432.0..504.0, UiAction::Move),
            (512.0..600.0, UiAction::Delete),
        ]
        .into_iter()
        .find_map(|(range, action)| range.contains(&x).then_some(action));
    }
    if x < 24.0 || x >= 696.0 || y < LIST_TOP {
        return None;
    }
    let row = ((y - LIST_TOP) / ROW_HEIGHT) as usize;
    (row < MAX_VISIBLE_ROWS).then_some(UiAction::Select(row))
}

#[cfg(test)]
mod tests {
    use super::{action_for_point, action_for_point_in, UiAction};

    #[test]
    fn maps_toolbar_buttons() {
        assert_eq!(action_for_point(40.0, 110.0), Some(UiAction::Up));
        assert_eq!(action_for_point(120.0, 110.0), Some(UiAction::Open));
        assert_eq!(action_for_point(200.0, 110.0), Some(UiAction::Create));
        assert_eq!(action_for_point(290.0, 110.0), Some(UiAction::Rename));
        assert_eq!(action_for_point(380.0, 110.0), Some(UiAction::Copy));
        assert_eq!(action_for_point(460.0, 110.0), Some(UiAction::Move));
        assert_eq!(action_for_point(550.0, 110.0), Some(UiAction::Delete));
    }

    #[test]
    fn maps_visible_rows() {
        assert_eq!(action_for_point(100.0, 180.0), Some(UiAction::Select(0)));
        assert_eq!(action_for_point(100.0, 244.0), Some(UiAction::Select(1)));
        assert_eq!(action_for_point(100.0, 372.0), Some(UiAction::Select(3)));
    }

    #[test]
    fn ignores_gaps_and_outside_points() {
        assert_eq!(action_for_point(92.0, 110.0), None);
        assert_eq!(action_for_point(700.0, 110.0), None);
        assert_eq!(action_for_point(100.0, 700.0), None);
        assert_eq!(action_for_point(100.0, 20.0), None);
    }

    #[test]
    fn maps_narrow_two_row_toolbar() {
        assert_eq!(action_for_point_in(40.0, 110.0, 348.0), Some(UiAction::Up));
        assert_eq!(action_for_point_in(40.0, 160.0, 348.0), Some(UiAction::Copy));
        assert_eq!(action_for_point_in(180.0, 160.0, 348.0), Some(UiAction::Delete));
    }

    #[test]
    fn maps_narrow_icon_grid() {
        // 2x3 grid starting at y=200. Cell ~161x88.
        assert_eq!(action_for_point_in(40.0, 230.0, 326.0), Some(UiAction::Select(0)));
        assert_eq!(action_for_point_in(200.0, 230.0, 326.0), Some(UiAction::Select(1)));
        assert_eq!(action_for_point_in(40.0, 326.0, 326.0), Some(UiAction::Select(2)));
        assert_eq!(action_for_point_in(200.0, 326.0, 326.0), Some(UiAction::Select(3)));
        assert_eq!(action_for_point_in(20.0, 190.0, 326.0), None);
    }
}
