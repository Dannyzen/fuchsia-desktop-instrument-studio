// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LayoutConfig {
    pub gap_px: u32,
    pub active_border_px: u32,
    pub wrap_focus: bool,
}

impl Default for LayoutConfig {
    fn default() -> Self {
        Self { gap_px: 12, active_border_px: 3, wrap_focus: true }
    }
}

impl LayoutConfig {
    pub fn validate(self) -> Result<(), String> {
        if self.gap_px > 128 {
            return Err(format!("gap must be at most 128 pixels, got {}", self.gap_px));
        }
        if !(1..=16).contains(&self.active_border_px) {
            return Err(format!(
                "active border must be between 1 and 16 pixels, got {}",
                self.active_border_px
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Size {
    pub width: u32,
    pub height: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LayoutSlot {
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
    pub content_inset: u32,
}

#[cfg(test)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Direction {
    Up,
    Down,
    Left,
    Right,
}

#[derive(Debug)]
pub struct WindowPolicy {
    #[cfg(test)]
    config: LayoutConfig,
    order: Vec<String>,
    focused: Option<String>,
    confirmed_focus: Option<String>,
}

impl WindowPolicy {
    pub fn new(config: LayoutConfig) -> Result<Self, String> {
        config.validate()?;
        Ok(Self {
            #[cfg(test)]
            config,
            order: Vec::new(),
            focused: None,
            confirmed_focus: None,
        })
    }

    #[cfg(test)]
    pub fn add(&mut self, id: String) {
        if self.order.iter().any(|existing| existing == &id) {
            return;
        }
        self.order.push(id.clone());
        if self.focused.is_none() {
            self.focused = Some(id);
        }
    }

    pub fn add_front(&mut self, id: String) {
        if self.order.iter().any(|existing| existing == &id) {
            return;
        }
        let should_focus = self.focused.is_none();
        self.order.insert(0, id.clone());
        if should_focus {
            self.focused = Some(id);
        }
    }

    pub fn remove(&mut self, id: &str) {
        let Some(position) = self.order.iter().position(|existing| existing == id) else {
            return;
        };
        let removed_was_focused = self.focused.as_deref() == Some(id);
        if self.confirmed_focus.as_deref() == Some(id) {
            self.confirmed_focus = None;
        }
        self.order.remove(position);
        if removed_was_focused {
            self.focused = if self.order.is_empty() {
                None
            } else {
                Some(self.order[position.min(self.order.len() - 1)].clone())
            };
        }
    }

    #[cfg(test)]
    pub fn focus_position(&mut self, position: usize) -> Result<&str, String> {
        let id = self
            .order
            .get(position)
            .cloned()
            .ok_or_else(|| format!("focus position {position} is out of bounds"))?;
        self.focused = Some(id);
        Ok(self.focused.as_deref().expect("focus set above"))
    }

    pub fn set_order(&mut self, old_position: usize, new_position: usize) -> Result<(), String> {
        if old_position >= self.order.len() || new_position >= self.order.len() {
            return Err(format!(
                "order positions must be within 0..{}, got {old_position}->{new_position}",
                self.order.len()
            ));
        }
        if old_position == new_position {
            return Ok(());
        }
        let id = self.order.remove(old_position);
        self.order.insert(new_position, id);
        Ok(())
    }

    pub fn cycle_order(&mut self) -> Result<(), String> {
        if self.order.is_empty() {
            return Err("cannot cycle an empty layout".to_string());
        }
        self.set_order(0, self.order.len() - 1)
    }

    #[cfg(test)]
    pub fn focus_direction(&mut self, direction: Direction) -> Result<&str, String> {
        if self.order.is_empty() {
            return Err("cannot focus an empty layout".to_string());
        }
        let current = self
            .focused
            .as_ref()
            .and_then(|focused| self.order.iter().position(|id| id == focused))
            .unwrap_or(0);
        let columns = (self.order.len() as f32).sqrt().ceil() as usize;
        let rows = self.order.len().div_ceil(columns);
        let row = current / columns;
        let column = current % columns;
        let candidate = match direction {
            Direction::Left => {
                if column > 0 {
                    current - 1
                } else if self.config.wrap_focus {
                    row * columns + row_len(self.order.len(), columns, row) - 1
                } else {
                    current
                }
            }
            Direction::Right => {
                let length = row_len(self.order.len(), columns, row);
                if column + 1 < length {
                    current + 1
                } else if self.config.wrap_focus {
                    row * columns
                } else {
                    current
                }
            }
            Direction::Up => {
                if row > 0 {
                    ((row - 1) * columns + column).min(self.order.len() - 1)
                } else if self.config.wrap_focus {
                    ((rows - 1) * columns + column).min(self.order.len() - 1)
                } else {
                    current
                }
            }
            Direction::Down => {
                if row + 1 < rows {
                    ((row + 1) * columns + column).min(self.order.len() - 1)
                } else if self.config.wrap_focus {
                    column.min(self.order.len() - 1)
                } else {
                    current
                }
            }
        };
        self.focus_position(candidate)
    }

    pub fn confirm_focus(&mut self, id: &str) -> Result<(), String> {
        if !self.order.iter().any(|candidate| candidate == id) {
            return Err(format!("cannot confirm unknown tile {id}"));
        }
        self.focused = Some(id.to_string());
        self.confirmed_focus = Some(id.to_string());
        Ok(())
    }

    pub fn clear_confirmed_focus(&mut self) {
        self.confirmed_focus = None;
    }

    pub fn confirmed_focus_id(&self) -> Option<&str> {
        self.confirmed_focus.as_deref()
    }

    pub fn focused_id(&self) -> Option<&str> {
        self.focused.as_deref()
    }

    #[cfg(test)]
    pub fn focused_position(&self) -> Option<usize> {
        self.focused.as_ref().and_then(|focused| self.order.iter().position(|id| id == focused))
    }

    pub fn order(&self) -> Vec<&str> {
        self.order.iter().map(String::as_str).collect()
    }
}

fn row_len(tile_count: usize, columns: usize, row: usize) -> usize {
    (tile_count - row * columns).min(columns)
}

pub fn compute_layout(
    display: Size,
    tile_count: usize,
    config: LayoutConfig,
) -> Result<Vec<LayoutSlot>, String> {
    config.validate()?;
    if tile_count == 0 {
        return Ok(Vec::new());
    }
    if display.width == 0 || display.height == 0 {
        return Err("display dimensions must be non-zero".to_string());
    }
    if tile_count == 1 {
        return Ok(vec![LayoutSlot {
            x: 0,
            y: 0,
            width: display.width,
            height: display.height,
            content_inset: 0,
        }]);
    }

    let mut columns = (tile_count as f32).sqrt().ceil() as usize;
    let mut rows = tile_count.div_ceil(columns);
    if display.height > display.width {
        std::mem::swap(&mut columns, &mut rows);
    }

    let vertical_gap_total = config.gap_px.saturating_mul(rows as u32 + 1);
    let usable_height = display
        .height
        .checked_sub(vertical_gap_total)
        .ok_or_else(|| "gap policy leaves no vertical tile space".to_string())?;
    let tile_height = usable_height / rows as u32;
    if tile_height <= config.active_border_px.saturating_mul(2) {
        return Err("active border leaves no vertical content space".to_string());
    }

    let mut slots = Vec::with_capacity(tile_count);
    let mut index = 0usize;
    for row in 0..rows {
        let tiles_in_row = row_len(tile_count, columns, row);
        if tiles_in_row == 0 {
            continue;
        }
        let horizontal_gap_total = config.gap_px.saturating_mul(tiles_in_row as u32 + 1);
        let usable_width = display
            .width
            .checked_sub(horizontal_gap_total)
            .ok_or_else(|| "gap policy leaves no horizontal tile space".to_string())?;
        let tile_width = usable_width / tiles_in_row as u32;
        if tile_width <= config.active_border_px.saturating_mul(2) {
            return Err("active border leaves no horizontal content space".to_string());
        }
        for column in 0..tiles_in_row {
            if index == tile_count {
                break;
            }
            slots.push(LayoutSlot {
                x: config.gap_px + column as u32 * (tile_width + config.gap_px),
                y: config.gap_px + row as u32 * (tile_height + config.gap_px),
                width: tile_width,
                height: tile_height,
                content_inset: config.active_border_px,
            });
            index += 1;
        }
    }
    Ok(slots)
}

#[cfg(test)]
mod tests {
    use super::{Direction, LayoutConfig, LayoutSlot, Size, WindowPolicy, compute_layout};

    fn four_tiles() -> WindowPolicy {
        let mut policy = WindowPolicy::new(LayoutConfig::default()).expect("valid defaults");
        for id in ["browser", "terminal", "files", "settings"] {
            policy.add(id.to_string());
        }
        policy
    }

    #[test]
    fn default_policy_has_visible_bounded_gaps_and_border() {
        let config = LayoutConfig::default();
        assert!(config.gap_px >= 8);
        assert!(config.active_border_px >= 2);
        assert!(config.validate().is_ok());
    }

    #[test]
    fn invalid_layout_settings_fail_closed() {
        let invalid = LayoutConfig { gap_px: 400, active_border_px: 24, wrap_focus: true };
        let error = WindowPolicy::new(invalid).expect_err("oversized layout policy must fail");
        assert!(error.contains("gap"));
    }

    #[test]
    fn single_tile_uses_fullscreen_smart_gaps_for_compatibility() {
        let slots = compute_layout(Size { width: 720, height: 1200 }, 1, LayoutConfig::default())
            .expect("single tile layout");
        assert_eq!(
            slots,
            vec![LayoutSlot { x: 0, y: 0, width: 720, height: 1200, content_inset: 0 }]
        );
    }

    #[test]
    fn four_tile_portrait_layout_reserves_outer_gaps_and_border_insets() {
        let config = LayoutConfig { gap_px: 12, active_border_px: 3, wrap_focus: true };
        let slots =
            compute_layout(Size { width: 720, height: 1200 }, 4, config).expect("four tile layout");
        assert_eq!(slots.len(), 4);
        assert_eq!((slots[0].x, slots[0].y, slots[0].width, slots[0].height), (12, 12, 342, 582));
        assert_eq!((slots[1].x, slots[1].y), (366, 12));
        assert_eq!((slots[2].x, slots[2].y), (12, 606));
        assert_eq!((slots[3].x, slots[3].y), (366, 606));
        assert_eq!(slots[0].content_inset, 3);
    }

    #[test]
    fn selected_focus_is_not_confirmed_until_scenic_reports_it() {
        let mut policy = WindowPolicy::new(LayoutConfig::default()).expect("valid defaults");
        policy.add_front("browser".to_string());
        assert_eq!(policy.focused_id(), Some("browser"));
        assert_eq!(policy.confirmed_focus_id(), None);
        policy.confirm_focus("browser").expect("confirm browser");
        assert_eq!(policy.confirmed_focus_id(), Some("browser"));
    }

    #[test]
    fn removing_confirmed_focus_clears_visual_until_successor_is_confirmed() {
        let mut policy = four_tiles();
        policy.confirm_focus("files").expect("confirm files");
        assert_eq!(policy.confirmed_focus_id(), Some("files"));
        policy.remove("files");
        assert_eq!(policy.focused_id(), Some("settings"));
        assert_eq!(policy.confirmed_focus_id(), None);
        policy.confirm_focus("settings").expect("confirm successor");
        assert_eq!(policy.confirmed_focus_id(), Some("settings"));
    }

    #[test]
    fn front_insert_preserves_existing_active_identity() {
        let mut policy = WindowPolicy::new(LayoutConfig::default()).expect("valid defaults");
        policy.add_front("browser".to_string());
        policy.add_front("terminal".to_string());
        assert_eq!(policy.order(), ["terminal", "browser"]);
        assert_eq!(policy.focused_id(), Some("browser"));
        assert_eq!(policy.focused_position(), Some(1));
    }

    #[test]
    fn focus_tracks_tile_identity_through_reorder() {
        let mut policy = four_tiles();
        assert_eq!(policy.focus_position(2).expect("focus files"), "files");
        policy.set_order(2, 0).expect("move focused tile");
        assert_eq!(policy.focused_id(), Some("files"));
        assert_eq!(policy.focused_position(), Some(0));
        assert_eq!(policy.order(), ["files", "browser", "terminal", "settings"]);
    }

    #[test]
    fn invalid_focus_preserves_the_current_active_tile() {
        let mut policy = four_tiles();
        policy.focus_position(1).expect("focus terminal");
        assert!(policy.focus_position(99).is_err());
        assert_eq!(policy.focused_id(), Some("terminal"));
    }

    #[test]
    fn directional_focus_wraps_across_the_grid_without_reordering() {
        let mut policy = four_tiles();
        policy.focus_position(3).expect("focus settings");
        assert_eq!(policy.focus_direction(Direction::Right).expect("wrap right"), "files");
        assert_eq!(policy.focus_direction(Direction::Down).expect("wrap down"), "browser");
        assert_eq!(policy.order(), ["browser", "terminal", "files", "settings"]);
    }

    #[test]
    fn empty_cycle_is_rejected_without_underflow() {
        let mut policy = WindowPolicy::new(LayoutConfig::default()).expect("valid defaults");
        let error = policy.cycle_order().expect_err("empty cycle must fail safely");
        assert!(error.contains("empty"));
        assert!(policy.order().is_empty());
        assert_eq!(policy.focused_id(), None);
    }

    #[test]
    fn left_and_up_navigation_wrap_by_geometry() {
        let mut policy = four_tiles();
        policy.focus_position(0).expect("focus browser");
        assert_eq!(policy.focus_direction(Direction::Left).expect("wrap left"), "terminal");
        assert_eq!(policy.focus_direction(Direction::Up).expect("wrap up"), "settings");
    }

    #[test]
    fn removing_the_active_tile_selects_the_nearest_survivor() {
        let mut policy = four_tiles();
        policy.focus_position(2).expect("focus files");
        policy.remove("files");
        assert_eq!(policy.focused_id(), Some("settings"));
        policy.remove("settings");
        assert_eq!(policy.focused_id(), Some("terminal"));
    }
}
