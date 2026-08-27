// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use anyhow::{Context as _, Result, ensure};
use fidl_fuchsia_session_window as window;
use fuchsia_component::client::connect_to_protocol;

#[fuchsia::main(logging = true)]
async fn main() -> Result<()> {
    let manager = connect_to_protocol::<window::ManagerMarker>()
        .context("connect to fuchsia.session.window.Manager")?;
    let before = manager.list().await.context("list windows before focus")?;
    ensure!(!before.is_empty(), "expected at least one window");

    let focus_position = before
        .iter()
        .position(|view| view.id.to_ascii_lowercase().contains("terminal"))
        .context("terminal window not found")? as u64;
    let focused_id = before[focus_position as usize].id.clone();
    manager.focus(focus_position).await.context("focus terminal window")?;
    manager.set_order(focus_position, 0).await.context("move focused window to position 0")?;

    let after = manager.list().await.context("list windows after reorder")?;
    ensure!(after.len() == before.len(), "window count changed during reorder");
    ensure!(after[0].id == focused_id, "focused window did not move to position 0");
    log::info!("TILING_WM_DRIVER_DONE focused_id={focused_id} position=0 count={}", after.len());
    Ok(())
}
