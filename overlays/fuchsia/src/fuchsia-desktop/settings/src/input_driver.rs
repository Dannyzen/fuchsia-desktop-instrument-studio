// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use anyhow::{Context as _, Result};
use fidl_fuchsia_math as fmath;
use fidl_fuchsia_ui_test_input::{
    CoordinateUnit, RegistryMarker, RegistryRegisterTouchScreenRequest, TouchScreenMarker,
    TouchScreenSimulateTapRequest,
};
use fuchsia_component::client::connect_to_protocol;

async fn tap(touch: &fidl_fuchsia_ui_test_input::TouchScreenProxy, x: i32, y: i32) -> Result<()> {
    touch
        .simulate_tap(&TouchScreenSimulateTapRequest {
            tap_location: Some(fmath::Vec_ { x, y }),
            ..Default::default()
        })
        .await
        .with_context(|| format!("tap ({x}, {y})"))?;
    fuchsia_async::Timer::new(zx::MonotonicDuration::from_millis(300)).await;
    Ok(())
}

#[fuchsia::main(logging = true)]
async fn main() -> Result<()> {
    let registry = connect_to_protocol::<RegistryMarker>().context("connect input registry")?;
    let (touch, touch_server) = fidl::endpoints::create_proxy::<TouchScreenMarker>();
    registry
        .register_touch_screen(RegistryRegisterTouchScreenRequest {
            device: Some(touch_server),
            coordinate_unit: Some(CoordinateUnit::PhysicalPixels),
            ..Default::default()
        })
        .await
        .context("register synthetic touchscreen")?;

    // End in the accepted persisted state regardless of the starting state.
    for (x, y) in [(180, 230), (430, 230), (180, 390), (430, 390)] {
        tap(&touch, x, y).await?;
    }
    log::info!("Completed backed Settings touch journey");
    Ok(())
}
